import argparse
import csv
import html
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

BASE_URL = os.getenv("VIGILO_BASE_URL", "http://182.23.67.40/vigilo").rstrip("/")
LOGIN_PATH = os.getenv("VIGILO_LOGIN_PATH", "slave_login.php")
USERNAME = os.getenv("VIGILO_USERNAME", "")
PASSWORD = os.getenv("VIGILO_PASSWORD", "")
LANGUAGE = os.getenv("VIGILO_LANGUAGE", "ID")
THEME = os.getenv("VIGILO_THEME", "skyblue")
SESSION_FILE = ROOT / os.getenv("VIGILO_SESSION_FILE", "session.json")
KEEPALIVE_SECONDS = int(os.getenv("VIGILO_KEEPALIVE_SECONDS", "240"))
TASKS_FILE = Path(os.getenv("VIGILO_TASKS_FILE", str(ROOT / "tasks.csv")))
DEFAULT_DEVELOPER = os.getenv("VIGILO_DEVELOPER", "0000000021")

EXPIRED_MARKERS = ("session has expired", "press refresh")

TASK_PAGE = "task_3task.php"
TASK_ENDPOINT = "task_slave_3task.php"
PAR = BASE_URL.replace("http://", "").replace("https://", "") + "/" + TASK_PAGE

SELECT_IDS = ["idclient", "idmodul", "tipetask", "developer", "qcsupervisi"]
DURATION = {"easy": 1, "medium": 3, "hard": 7, "super hard": 10}

CSV_HEADER = ["client", "modul", "task", "tipe", "developer", "qc", "deadline"]
CSV_DELIMITER = ";"
PROGRESS_HEADER = ["idtask", "progress", "keterangan", "task"]
PROGRESS_FILE = Path(os.getenv("VIGILO_PROGRESS_FILE", str(ROOT / "progress.csv")))


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GREY = "\033[90m"
    BBLUE = "\033[94m"
    BGREEN = "\033[92m"
    BRED = "\033[91m"
    BYELLOW = "\033[93m"
    BCYAN = "\033[96m"


def _enable_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes

        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass


_enable_ansi()
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
COLOR_ON = not os.environ.get("NO_COLOR")


def paint(text, *styles):
    if not COLOR_ON or not styles:
        return str(text)
    return "".join(styles) + str(text) + C.RESET


def url(path):
    return f"{BASE_URL}/{path.lstrip('/')}"


def new_session():
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Referer": url("login.html"),
        }
    )
    return s


def save_session(session):
    data = {c.name: c.value for c in session.cookies}
    SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_session():
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not data:
        return None
    s = new_session()
    for k, v in data.items():
        s.cookies.set(k, v, domain="182.23.67.40", path="/")
    return s


def is_expired(text):
    low = text.lower()
    return any(m in low for m in EXPIRED_MARKERS)


def is_save_ok(text):
    t = text.strip().upper()
    return not (t.startswith("GAGAL") or t.startswith("ERROR") or t.startswith("WARNING"))


def login(session=None, verbose=True):
    if not USERNAME or not PASSWORD:
        raise SystemExit("VIGILO_USERNAME / VIGILO_PASSWORD belum diisi di .env")
    s = session or new_session()
    payload = {
        "uname": USERNAME,
        "password": PASSWORD,
        "language": LANGUAGE,
        "theme": THEME,
        "par": BASE_URL.replace("http://", "").replace("https://", ""),
    }
    resp = s.post(url(LOGIN_PATH), data=payload)
    body = resp.text.strip()
    if "wrong" in body.lower():
        raise SystemExit(f"Login gagal: {body}")
    save_session(s)
    if verbose:
        print(f"[login] berhasil, session disimpan ke {SESSION_FILE.name}")
    return s


def ensure_session(session=None, verbose=True):
    s = session or load_session()
    if s is None:
        return login(verbose=verbose)
    resp = s.get(url("master.php"))
    if is_expired(resp.text):
        if verbose:
            print("[session] expired, login ulang...")
        return login(session=s, verbose=verbose)
    if verbose:
        print("[session] masih valid")
    save_session(s)
    return s


PHP_REF = re.compile(r"['\"]([A-Za-z0-9_]+\.php)(?:\?[^'\"]*)?['\"]")
SELECT_RE = re.compile(r"<select[^>]*id=['\"]?([A-Za-z0-9_]+)['\"]?[^>]*>(.*?)</select>", re.S | re.I)
OPTION_RE = re.compile(r"<option[^>]*value=['\"]?([^'\">]*)['\"]?[^>]*>(.*?)</option>", re.S | re.I)


def recon(session):
    session = ensure_session(session)
    print(f"[recon] GET {url('master.php')}")
    master = session.get(url("master.php"))
    found = sorted(set(PHP_REF.findall(master.text)))
    out = ROOT / "recon_master.html"
    out.write_text(master.text, encoding="utf-8", errors="replace")
    print(f"[recon] {len(found)} endpoint ditemukan, HTML disimpan ke {out.name}")
    for name in found:
        print("   -", name)
    links = sorted(set(re.findall(r"['\"]([A-Za-z0-9_]+\.html)['\"]", master.text)))
    if links:
        print("[recon] halaman html:")
        for name in links:
            print("   -", name)


def fetch_options(session):
    html = session.get(url(TASK_PAGE)).text
    result = {}
    for sel_id, block in SELECT_RE.findall(html):
        if sel_id not in SELECT_IDS:
            continue
        options = []
        for value, label in OPTION_RE.findall(block):
            clean = re.sub(r"<[^>]+>", "", label).strip()
            if value.strip() == "":
                continue
            options.append((value.strip(), clean))
        result[sel_id] = options
    return result


def resolve(options, select_id, raw, required=True, label=""):
    raw = (raw or "").strip()
    if not raw:
        if required:
            raise ValueError(f"{label or select_id} wajib diisi")
        return ""
    opts = options.get(select_id, [])
    low = raw.lower()
    for value, _label in opts:
        if value.lower() == low:
            return value
    for value, olabel in opts:
        if olabel.lower() == low:
            return value
    for value, olabel in opts:
        if low in olabel.lower():
            return value
    raise ValueError(f"{raw!r} tidak dikenal untuk {label or select_id}")


def resolve_multi(options, select_id, raw, required=True, label=""):
    raw = (raw or "").strip()
    if not raw:
        if required:
            raise ValueError(f"{label or select_id} wajib diisi")
        return ""
    parts = re.split(r"[;,]", raw)
    ids = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        ids.append(resolve(options, select_id, part, required, label))
    if required and not ids:
        raise ValueError(f"{label or select_id} wajib diisi")
    return ",".join(ids)


def parse_deadline(raw, tipe):
    raw = (raw or "").strip()
    if raw:
        for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%d-%m-%Y")
            except ValueError:
                continue
        raise ValueError(f"deadline {raw!r} tidak valid (pakai dd-mm-yyyy)")
    days = DURATION.get(tipe.lower(), 1)
    return (datetime.now() + timedelta(days=days)).strftime("%d-%m-%Y")


def read_tasks(path):
    if not path.exists():
        raise SystemExit(f"File task tidak ditemukan: {path}. Jalankan: python vigilo.py template")
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        lines = [
            ln
            for ln in fh
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
    if not lines:
        return []
    first = lines[0]
    delimiter = CSV_DELIMITER if first.count(CSV_DELIMITER) >= first.count(",") else ","
    header = [h.strip().lower() for h in first.split(delimiter)]
    if header != CSV_HEADER:
        raise SystemExit(
            "Header tidak sesuai. Baris pertama data harus (pemisah "
            f"'{delimiter}'):\n  {delimiter.join(CSV_HEADER)}"
        )
    rows = []
    reader = csv.DictReader(lines, delimiter=delimiter)
    for idx, row in enumerate(reader, start=2):
        if None in row:
            raise SystemExit(
                f"Baris {idx}: jumlah kolom tidak sesuai header "
                f"(harus {len(CSV_HEADER)} kolom, pemisah '{delimiter}')."
            )
        if not any((v or "").strip() for v in row.values()):
            continue
        row["_row"] = idx
        rows.append(row)
    return rows


def build_payload(row, options):
    tipe = (row.get("tipe") or "").strip()
    tipetask = resolve(options, "tipetask", tipe, required=False, label="tipe") if tipe else ""
    payload = {
        "method": "insert",
        "idtask": "",
        "idclient": resolve(options, "idclient", row.get("client"), label="client"),
        "idmodul": resolve(options, "idmodul", row.get("modul"), label="modul"),
        "task": (row.get("task") or "").strip(),
        "tipetask": tipetask,
        "developer": resolve(options, "developer", row.get("developer"), label="developer"),
        "qcsupervisi": resolve_multi(options, "qcsupervisi", row.get("qc"), label="qc"),
        "deadline": parse_deadline(row.get("deadline"), tipe),
    }
    if not payload["task"]:
        raise ValueError("task wajib diisi")
    return payload


def cmd_options(session):
    session = ensure_session(session, verbose=False)
    options = fetch_options(session)
    for sel_id in SELECT_IDS:
        opts = options.get(sel_id, [])
        print(f"\n===== {sel_id} ({len(opts)}) =====")
        for value, label in opts:
            print(f"  {value:<12} {label}")


def _opt(options, sel_id, idx, fallback="", as_code=True):
    opts = options.get(sel_id, [])
    if not opts:
        return fallback
    value, label = opts[idx % len(opts)]
    return value if as_code else label


def cmd_template(args, session=None):
    if TASKS_FILE.exists() and not args.force:
        raise SystemExit(f"{TASKS_FILE.name} sudah ada. Pakai --force untuk menimpa.")
    session = ensure_session(session, verbose=False)
    options = fetch_options(session)

    codes = {sel: " | ".join(v for v, _ in options.get(sel, [])) for sel in SELECT_IDS}
    dev_legend = " ; ".join(f"{v}={l}" for v, l in options.get("developer", []))
    lines = [
        "# Template input task OWL-Plantation (hanya SIMPAN/insert, tanpa posting).",
        f"# Kolom (pemisah '{CSV_DELIMITER}'): {CSV_DELIMITER.join(CSV_HEADER)}",
        "#   client/modul/tipe : pakai ID/kode (bisa dikosongkan tipe)",
        "#   developer/qc      : pakai ID pegawai; qc boleh banyak, pisah koma di dalam sel",
        "#   deadline          : dd-mm-yyyy; kosongkan untuk otomatis dari tipe",
        "#",
        f"# ID client : {codes.get('idclient', '')}",
        f"# ID modul  : {codes.get('idmodul', '')}",
        f"# ID tipe   : {codes.get('tipetask', '')}",
        f"# ID developer/qc : {dev_legend}",
        "#",
        "# Contoh (masih dikomentari dengan #). Hapus '#' di awal baris untuk memakai:",
        "#",
        "# ⬇⬇⬇  Isi baris task Anda di bawah sini  ⬇⬇⬇",
    ]
    rows = [
        [
            _opt(options, "idclient", 0, "BKNS"),
            _opt(options, "idmodul", 3, "KEBUN"),
            "Contoh task deadline otomatis",
            _opt(options, "tipetask", 1, "medium"),
            _opt(options, "developer", 22, "0000000001"),
            ",".join(
                [
                    _opt(options, "qcsupervisi", 21, "0000000020"),
                    _opt(options, "qcsupervisi", 23, "0000000051"),
                ]
            ),
            "",
        ],
        [
            _opt(options, "idclient", 1, "CSU"),
            _opt(options, "idmodul", 4, "KEU"),
            "Contoh task deadline manual",
            _opt(options, "tipetask", 0, "easy"),
            _opt(options, "developer", 23, "0000000006"),
            _opt(options, "qcsupervisi", 3, "0000000029"),
            "31-12-2026",
        ],
    ]
    try:
        fh = TASKS_FILE.open("w", encoding="utf-8", newline="")
    except PermissionError:
        raise SystemExit(
            f"Tidak bisa menulis {TASKS_FILE.name}: file sedang dibuka program lain "
            "(mis. Excel). Tutup dulu lalu ulangi."
        )
    with fh:
        fh.write("\n".join(lines) + "\n")
        writer = csv.writer(fh, delimiter=CSV_DELIMITER)
        writer.writerow(CSV_HEADER)
        for row in rows:
            buf = io.StringIO()
            csv.writer(buf, delimiter=CSV_DELIMITER).writerow(row)
            fh.write("# " + buf.getvalue())
    print(f"[template] dibuat: {TASKS_FILE}")


def _fmt_table(headers, rows, title=None):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell[0]))

    def rule(left, mid, right, fill="─"):
        return left + mid.join(fill * (w + 2) for w in widths) + right

    out = []
    if title:
        out.append(paint("  " + title, C.BOLD, C.BBLUE))
    out.append("  " + paint(rule("┌", "┬", "┐"), C.GREY))
    out.append(
        "  "
        + paint("│", C.GREY)
        + paint("│", C.GREY).join(
            " " + paint(h.center(widths[i]), C.BOLD, C.BCYAN) + " "
            for i, h in enumerate(headers)
        )
        + paint("│", C.GREY)
    )
    out.append("  " + paint(rule("├", "┼", "┤"), C.GREY))
    for row in rows:
        cells = []
        for i, (text, style) in enumerate(row):
            cells.append(" " + paint(text.ljust(widths[i]), *(style or ())) + " ")
        out.append("  " + paint("│", C.GREY) + paint("│", C.GREY).join(cells) + paint("│", C.GREY))
    out.append("  " + paint(rule("└", "┴", "┘"), C.GREY))
    return "\n".join(out)


def cmd_add(args):
    session = ensure_session(verbose=False)
    options = fetch_options(session)
    if not options:
        raise SystemExit("Gagal memuat opsi dropdown. Cek sesi/login.")
    rows = read_tasks(TASKS_FILE)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print(paint("[add] tidak ada baris task.", C.YELLOW))
        return

    prepared, errors = [], []
    for row in rows:
        try:
            prepared.append((row["_row"], build_payload(row, options)))
        except (ValueError, KeyError) as exc:
            errors.append((row["_row"], str(exc)))

    headers = ["#", "CLIENT", "MODUL", "TIPE", "DEVELOPER", "QC", "DEADLINE", "TASK"]
    trows = [
        [
            (str(n), (C.GREY,)),
            (p["idclient"], (C.BGREEN,)),
            (p["idmodul"], (C.BGREEN,)),
            (p["tipetask"] or "-", (C.BYELLOW,)),
            (p["developer"], (C.BCYAN,)),
            (p["qcsupervisi"], (C.BCYAN,)),
            (p["deadline"], (C.MAGENTA,)),
            (p["task"], ()),
        ]
        for n, p in prepared
    ]
    print()
    print(_fmt_table(headers, trows, title=f"TASK DARI {TASKS_FILE.name}"))
    print(
        "  "
        + paint(f"valid: {len(prepared)}", C.BGREEN, C.BOLD)
        + paint("  |  ", C.GREY)
        + paint(f"gagal validasi: {len(errors)}", (C.BRED if errors else C.GREY), C.BOLD)
    )
    if errors:
        print()
        for n, msg in errors:
            print("  " + paint("✗", C.BRED) + paint(f" #{n} ", C.GREY) + paint(msg, C.RED))

    if not args.submit:
        print()
        print(paint("  DRY-RUN — tidak ada data dikirim. Tambahkan --submit untuk menyimpan.", C.BYELLOW, C.BOLD))
        print()
        return

    print()
    print(paint("  Mengirim (method=insert)...", C.BBLUE, C.BOLD))
    ok = fail = 0
    for n, payload in prepared:
        try:
            resp = session.post(url(TASK_ENDPOINT), data=payload)
            if is_expired(resp.text):
                session = login(session=session, verbose=False)
                resp = session.post(url(TASK_ENDPOINT), data=payload)
            if is_save_ok(resp.text):
                ok += 1
                print("  " + paint("✓", C.BGREEN) + paint(f" #{n} ", C.GREY) + paint("OK", C.BGREEN, C.BOLD))
            else:
                fail += 1
                print(
                    "  " + paint("✗", C.BRED) + paint(f" #{n} ", C.GREY)
                    + paint("GAGAL", C.BRED, C.BOLD) + paint(f" — {resp.text.strip()[:100]}", C.RED)
                )
        except requests.RequestException as exc:
            fail += 1
            print("  " + paint("✗", C.BRED) + paint(f" #{n} ", C.GREY) + paint(f"ERROR — {exc}", C.RED))
        time.sleep(args.delay)

    print()
    print(
        "  "
        + paint("SELESAI ", C.BOLD, C.BCYAN)
        + paint(f"sukses={ok}", C.BGREEN, C.BOLD)
        + paint("  ", C.GREY)
        + paint(f"gagal={fail}", (C.BRED if fail else C.GREY), C.BOLD)
    )
    print()


def _clean_cell(raw):
    return html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def fetch_task_list(session, developer="", status="belum_posting", client="", modul="", limit=0):
    found = []
    seen = set()
    page = 0
    while page < 100:
        param = {
            "method": "loaddata",
            "page": str(page),
            "crdeadlinedari": "",
            "crdeadlinesampai": "",
            "crestdari": "",
            "crestsampai": "",
            "crdeveloper": developer,
            "cridmodul": modul,
            "cridclient": client,
            "crqcsupervisi": "",
            "crprogressdeveloper": "",
            "crprogressqc": "",
            "crstatus": status,
            "par": PAR,
        }
        resp = session.post(url(TASK_ENDPOINT), data=param)
        if is_expired(resp.text):
            return found
        rows = re.findall(r"<tr class=rowcontent>(.*?)</tr>", resp.text, re.S)
        if not rows:
            break
        added = 0
        for row in rows:
            ids = re.findall(
                r"(?:posting|formProgress|formPicQc|formCancel|formDeadline|formFile|edit|taskHapus)\(['\"]?(\d+)",
                row,
            )
            cells = [_clean_cell(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if not ids or len(cells) < 12:
                continue
            idtask = ids[0]
            if idtask in seen:
                continue
            seen.add(idtask)
            added += 1
            found.append(
                {
                    "idtask": idtask,
                    "client": cells[1],
                    "modul": cells[2],
                    "task": cells[3],
                    "tipe": cells[4],
                    "pic": cells[5],
                    "qc": cells[6],
                    "progress_pic": cells[7],
                    "progress_qc": cells[8],
                    "estimasi": cells[9],
                    "deadline": cells[10],
                    "status": cells[11],
                }
            )
            if limit and len(found) >= limit:
                return found
        next_page = f"loaddata({page + 1})" in resp.text
        if added == 0 or not next_page:
            break
        page += 1
    return found


def _post_ids(session, tasks, delay):
    results = {}
    for i, t in enumerate(tasks, start=1):
        idtask = t["idtask"]
        try:
            resp = session.post(
                url(TASK_ENDPOINT), data={"method": "posting", "idtask": idtask, "par": PAR}
            )
            if is_expired(resp.text):
                session = login(session=session, verbose=False)
                resp = session.post(
                    url(TASK_ENDPOINT), data={"method": "posting", "idtask": idtask, "par": PAR}
                )
            ok = is_save_ok(resp.text)
            results[idtask] = ok
            if ok:
                print(
                    "  " + paint("✓", C.BGREEN) + paint(f" #{i} ", C.GREY)
                    + paint(idtask, C.BOLD, C.BCYAN) + " "
                    + paint("BERHASIL diposting", C.BGREEN, C.BOLD)
                    + paint(f" — {t['task'][:48]}", C.GREY)
                )
            else:
                print(
                    "  " + paint("✗", C.BRED) + paint(f" #{i} ", C.GREY)
                    + paint(idtask, C.BOLD, C.BCYAN) + " "
                    + paint("GAGAL", C.BRED, C.BOLD)
                    + paint(f" — {resp.text.strip()[:80]}", C.RED)
                )
        except requests.RequestException as exc:
            results[idtask] = False
            print(
                "  " + paint("✗", C.BRED) + paint(f" #{i} ", C.GREY)
                + paint(idtask, C.BOLD, C.BCYAN) + " "
                + paint(f"ERROR — {exc}", C.RED)
            )
        time.sleep(delay)
    return session, results


def cmd_post(args):
    session = ensure_session(verbose=False)
    tasks = fetch_task_list(
        session,
        developer=args.developer,
        status=args.status,
        client=args.client,
        modul=args.modul,
        limit=args.limit,
    )
    if not tasks:
        print(paint("  Tidak ada task yang cocok (belum diposting).", C.BYELLOW))
        return

    headers = ["#", "ID", "CLIENT", "MODUL", "TASK", "TIPE", "DEADLINE", "STATUS"]
    trows = [
        [
            (str(i), (C.GREY,)),
            (t["idtask"], (C.BOLD, C.BCYAN)),
            (t["client"], (C.BGREEN,)),
            (t["modul"], (C.BGREEN,)),
            (t["task"], ()),
            (t["tipe"].split(" (")[0], (C.BYELLOW,)),
            (t["deadline"], (C.MAGENTA,)),
            (t["status"], (C.BRED,)),
        ]
        for i, t in enumerate(tasks, start=1)
    ]
    print()
    print(_fmt_table(headers, trows, title=f"TASK BELUM DIPOSTING (PIC {args.developer})"))
    print(
        "  "
        + paint(f"total: {len(tasks)}", C.BGREEN, C.BOLD)
        + paint("  |  ", C.GREY)
        + paint("status: belum diposting", C.BRED, C.BOLD)
    )
    print(
        "  "
        + paint("PERINGATAN: data yang sudah diposting TIDAK dapat diubah/dibatalkan.", C.BYELLOW, C.BOLD)
    )

    if not args.submit:
        print()
        print(paint("  DRY-RUN — tidak ada data dikirim. Tambahkan --submit untuk posting.", C.BYELLOW, C.BOLD))
        print()
        return

    answer = input(
        "  " + paint(f"Ketik POSTING untuk memposting {len(tasks)} task: ", C.BOLD, C.BCYAN)
    ).strip()
    if answer != "POSTING":
        print(paint("  Dibatalkan. Tidak ada yang dikirim.", C.YELLOW))
        return

    ids = [t["idtask"] for t in tasks]
    print()
    print(paint("  Memposting (method=posting)...", C.BBLUE, C.BOLD))
    session, results = _post_ids(session, tasks, args.delay)

    print()
    print(paint("  Verifikasi ulang...", C.BBLUE, C.BOLD))
    remaining = {t["idtask"] for t in fetch_task_list(session, developer=args.developer, status="belum_posting")}
    posted = {t["idtask"] for t in fetch_task_list(session, developer=args.developer, status="sudah_posting")}

    ok = fail = 0
    for idtask in ids:
        verified = idtask in posted or idtask not in remaining
        if verified and results.get(idtask):
            ok += 1
        else:
            fail += 1
            reason = "respons gagal" if not results.get(idtask) else "masih belum diposting"
            print("  " + paint("✗", C.BRED) + paint(f" {idtask} ", C.GREY) + paint(reason, C.BRED, C.BOLD))

    print()
    print(
        "  "
        + paint("SELESAI ", C.BOLD, C.BCYAN)
        + paint(f"sukses={ok}", C.BGREEN, C.BOLD)
        + paint("  ", C.GREY)
        + paint(f"gagal={fail}", (C.BRED if fail else C.GREY), C.BOLD)
    )
    print()


def read_progress(path):
    if not path.exists():
        raise SystemExit(
            f"File progress tidak ditemukan: {path}. Jalankan: python vigilo.py progress --template"
        )
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    first = lines[0]
    delimiter = CSV_DELIMITER if first.count(CSV_DELIMITER) >= first.count(",") else ","
    header = [h.strip().lower() for h in first.split(delimiter)]
    if header != PROGRESS_HEADER:
        raise SystemExit(
            "Header progress tidak sesuai. Baris pertama data harus (pemisah "
            f"'{delimiter}'):\n  {delimiter.join(PROGRESS_HEADER)}"
        )
    rows = []
    reader = csv.DictReader(lines, delimiter=delimiter)
    for idx, row in enumerate(reader, start=2):
        if None in row:
            raise SystemExit(f"Baris {idx}: jumlah kolom tidak sesuai header progress.")
        if not any((v or "").strip() for v in row.values()):
            continue
        row["_row"] = idx
        rows.append(row)
    return rows


def cmd_progress_template(args):
    session = ensure_session(verbose=False)
    tasks = fetch_task_list(session, developer=args.developer, status="sudah_posting")
    if not tasks:
        raise SystemExit("Tidak ada task berstatus 'sudah diposting' untuk PIC tersebut.")
    out = Path(args.file)
    if out.exists() and not args.force:
        raise SystemExit(f"{out.name} sudah ada. Pakai --force untuk menimpa.")
    try:
        fh = out.open("w", encoding="utf-8", newline="")
    except PermissionError:
        raise SystemExit(f"Tidak bisa menulis {out.name}: file sedang dibuka program lain.")
    with fh:
        fh.write("# File progress task (progresstipe=developer).\n")
        fh.write(f"# PIC: {args.developer} | {len(tasks)} task berstatus sudah diposting.\n")
        fh.write("# Isi kolom progress (0-100) dan keterangan, lalu jalankan:\n")
        fh.write("#   python vigilo.py progress            (dry-run)\n")
        fh.write("#   python vigilo.py progress --submit   (kirim)\n")
        fh.write("# Kolom 'task' hanya informasi, tidak dikirim.\n")
        fh.write(f"# {' ; '.join(PROGRESS_HEADER)}\n")
        writer = csv.writer(fh, delimiter=CSV_DELIMITER)
        writer.writerow(PROGRESS_HEADER)
        for t in tasks:
            writer.writerow([t["idtask"], "", "", t["task"]])
    print(paint(f"  [progress] template dibuat: {out} ({len(tasks)} task)", C.BGREEN, C.BOLD))


def cmd_progress(args):
    rows = read_progress(Path(args.file))
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print(paint("  [progress] tidak ada baris.", C.YELLOW))
        return

    session = ensure_session(verbose=False)
    tasks = fetch_task_list(session, developer=args.developer, status="sudah_posting")
    valid_ids = {t["idtask"] for t in tasks}

    prepared, errors = [], []
    for row in rows:
        idtask = (row.get("idtask") or "").strip()
        progress = (row.get("progress") or "").strip()
        keterangan = (row.get("keterangan") or "").strip()
        label = (row.get("task") or "").strip()
        try:
            if not idtask:
                raise ValueError("idtask wajib diisi")
            if idtask not in valid_ids:
                raise ValueError(
                    f"idtask {idtask} tidak bisa diisi progress (bukan 'Sudah Diposting', "
                    "mungkin sudah 100%/PIC Selesai/DONE atau bukan milik Anda)"
                )
            if progress == "":
                raise ValueError("progress wajib diisi")
            if not progress.isdigit() or not (0 <= int(progress) <= 100):
                raise ValueError("progress harus angka 0-100")
            if not keterangan:
                raise ValueError("keterangan wajib diisi")
            prepared.append(
                {"idtask": idtask, "progress": progress, "keterangan": keterangan, "task": label}
            )
        except ValueError as exc:
            errors.append((row["_row"], exc))

    headers = ["#", "ID", "PROGRESS", "KETERANGAN", "TASK"]
    trows = [
        [
            (str(i), (C.GREY,)),
            (p["idtask"], (C.BOLD, C.BCYAN)),
            (f"{p['progress']}%", (C.BGREEN, C.BOLD)),
            (p["keterangan"], ()),
            (p["task"], (C.GREY,)),
        ]
        for i, p in enumerate(prepared, start=1)
    ]
    print()
    print(_fmt_table(headers, trows, title=f"PROGRESS DARI {Path(args.file).name}"))
    print(
        "  "
        + paint(f"valid: {len(prepared)}", C.BGREEN, C.BOLD)
        + paint("  |  ", C.GREY)
        + paint(f"gagal validasi: {len(errors)}", (C.BRED if errors else C.GREY), C.BOLD)
    )
    for n, msg in errors:
        print("  " + paint("✗", C.BRED) + paint(f" #{n} ", C.GREY) + paint(str(msg), C.RED))

    if not args.submit:
        print()
        print(paint("  DRY-RUN — tidak ada data dikirim. Tambahkan --submit untuk menyimpan.", C.BYELLOW, C.BOLD))
        print()
        return

    if not prepared:
        print(paint("  Tidak ada baris valid untuk dikirim.", C.YELLOW))
        return

    print()
    print(paint(f"  Menyimpan progress (progresstipe={args.tipe})...", C.BBLUE, C.BOLD))
    ok = fail = 0
    results = {}
    for i, p in enumerate(prepared, start=1):
        payload = {
            "method": "simpan_progress",
            "idtask": p["idtask"],
            "progresstipe": args.tipe,
            "progress": p["progress"],
            "keterangan": p["keterangan"],
            "par": PAR,
        }
        try:
            resp = session.post(url(TASK_ENDPOINT), data=payload)
            if is_expired(resp.text):
                session = login(session=session, verbose=False)
                resp = session.post(url(TASK_ENDPOINT), data=payload)
            good = is_save_ok(resp.text)
            results[p["idtask"]] = good
            if good:
                ok += 1
                print(
                    "  " + paint("✓", C.BGREEN) + paint(f" #{i} ", C.GREY)
                    + paint(p["idtask"], C.BOLD, C.BCYAN) + " "
                    + paint(f"BERHASIL disimpan ({p['progress']}%)", C.BGREEN, C.BOLD)
                    + paint(f" — {p['keterangan'][:44]}", C.GREY)
                )
            else:
                fail += 1
                print(
                    "  " + paint("✗", C.BRED) + paint(f" #{i} ", C.GREY)
                    + paint(p["idtask"], C.BOLD, C.BCYAN) + " "
                    + paint("GAGAL", C.BRED, C.BOLD)
                    + paint(f" — {resp.text.strip()[:80]}", C.RED)
                )
        except requests.RequestException as exc:
            fail += 1
            results[p["idtask"]] = False
            print("  " + paint("✗", C.BRED) + paint(f" #{i} ", C.GREY) + paint(f"ERROR — {exc}", C.RED))
        time.sleep(args.delay)

    print()
    print(paint("  Verifikasi ulang...", C.BBLUE, C.BOLD))
    after = {}
    for st in ("sudah_posting", "pic_selesai", "done"):
        for t in fetch_task_list(session, developer=args.developer, status=st):
            after[t["idtask"]] = (t["progress_pic"], t["status"])
    vok = vfail = 0
    for p in prepared:
        current, status = after.get(p["idtask"], ("", ""))
        target = f"{p['progress']}%"
        if results.get(p["idtask"]) and current.startswith(target):
            vok += 1
            print(
                "  " + paint("✓", C.BGREEN) + paint(f" {p['idtask']} ", C.GREY)
                + paint(current, C.BGREEN, C.BOLD)
                + paint(f" ({status})", C.GREY)
            )
        else:
            vfail += 1
            print(
                "  " + paint("✗", C.BRED) + paint(f" {p['idtask']} ", C.GREY)
                + paint(f"terbaca '{current}' (target {target})", C.BRED, C.BOLD)
            )

    print()
    print(
        "  "
        + paint("SELESAI ", C.BOLD, C.BCYAN)
        + paint(f"sukses={vok}", C.BGREEN, C.BOLD)
        + paint("  ", C.GREY)
        + paint(f"gagal={vfail}", (C.BRED if vfail else C.GREY), C.BOLD)
    )
    print()


def keepalive(session):
    session = ensure_session(session)
    print(f"[keepalive] tiap {KEEPALIVE_SECONDS}s, Ctrl+C untuk stop")
    try:
        while True:
            time.sleep(KEEPALIVE_SECONDS)
            resp = session.get(url("master.php"))
            status = "expired" if is_expired(resp.text) else "ok"
            print(f"[keepalive] {time.strftime('%H:%M:%S')} -> {status}")
            if status == "expired":
                session = login(session=session)
    except KeyboardInterrupt:
        print("\n[keepalive] dihentikan")


def main():
    global TASKS_FILE
    parser = argparse.ArgumentParser(description="VIGILO-Plantation automation")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("recon", help="enumerasi endpoint setelah login")
    sub.add_parser("keepalive", help="jaga sesi tetap hidup")
    sub.add_parser("options", help="tampilkan pilihan valid client/modul/tipe/developer/qc")

    p_tpl = sub.add_parser("template", help="buat file tasks.csv")
    p_tpl.add_argument("--force", action="store_true", help="timpa jika sudah ada")

    p_add = sub.add_parser("add", help="loop input task dari tasks.csv (insert saja)")
    p_add.add_argument("--submit", action="store_true", help="benar-benar kirim (default dry-run)")
    p_add.add_argument("--limit", type=int, default=0, help="batasi jumlah baris")
    p_add.add_argument("--delay", type=float, default=0.5, help="jeda antar submit (detik)")
    p_add.add_argument("--file", type=Path, default=TASKS_FILE, help="path file task")

    p_post = sub.add_parser("post", help="posting task yang belum diposting (permanen)")
    p_post.add_argument("--submit", action="store_true", help="benar-benar posting (default dry-run)")
    p_post.add_argument("--limit", type=int, default=0, help="batasi jumlah task")
    p_post.add_argument("--delay", type=float, default=0.5, help="jeda antar posting (detik)")
    p_post.add_argument("--developer", default=DEFAULT_DEVELOPER, help="filter PIC/developer")
    p_post.add_argument("--status", default="belum_posting", help="filter status task")
    p_post.add_argument("--client", default="", help="filter kode client")
    p_post.add_argument("--modul", default="", help="filter kode modul")

    p_prog = sub.add_parser("progress", help="input progress task yang sudah diposting")
    p_prog.add_argument("--submit", action="store_true", help="benar-benar simpan (default dry-run)")
    p_prog.add_argument("--template", action="store_true", help="generate progress.csv dari task posted")
    p_prog.add_argument("--force", action="store_true", help="timpa file saat --template")
    p_prog.add_argument("--file", type=Path, default=PROGRESS_FILE, help="file progress")
    p_prog.add_argument("--tipe", default="developer", choices=["developer", "qc"], help="tipe progress")
    p_prog.add_argument("--developer", default=DEFAULT_DEVELOPER, help="filter PIC/developer")
    p_prog.add_argument("--limit", type=int, default=0, help="batasi jumlah baris")
    p_prog.add_argument("--delay", type=float, default=0.5, help="jeda antar simpan (detik)")

    args = parser.parse_args()

    if args.cmd == "recon":
        recon(None)
    elif args.cmd == "keepalive":
        keepalive(None)
    elif args.cmd == "options":
        cmd_options(None)
    elif args.cmd == "template":
        cmd_template(args)
    elif args.cmd == "add":
        TASKS_FILE = args.file
        cmd_add(args)
    elif args.cmd == "post":
        cmd_post(args)
    elif args.cmd == "progress":
        if args.template:
            cmd_progress_template(args)
        else:
            cmd_progress(args)


if __name__ == "__main__":
    main()
