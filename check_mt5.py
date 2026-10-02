"""ตรวจหาสาเหตุที่ Python เชื่อมต่อ MetaTrader 5 ไม่ได้
วิธีใช้: เปิด MT5 และล็อกอินไว้ก่อน แล้วรัน  python check_mt5.py
"""
import ctypes
import platform
import struct
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def line(t=""):
    print(t, flush=True)


line("=== ตรวจการเชื่อมต่อ MT5 ===")
line(f"Python {platform.python_version()} ({struct.calcsize('P') * 8}-bit)")
if struct.calcsize("P") * 8 != 64:
    line("❌ ต้องใช้ Python แบบ 64-bit ติดตั้ง Python 3.12 (64-bit) ใหม่")

try:
    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
except Exception:
    is_admin = False
line(f"หน้าต่างนี้รันแบบ Administrator: {'ใช่' if is_admin else 'ไม่ใช่'}")

try:
    import MetaTrader5 as mt5
    line(f"แพ็กเกจ MetaTrader5 เวอร์ชัน {getattr(mt5, '__version__', '?')}")
except Exception as e:
    line(f"❌ import MetaTrader5 ไม่ได้: {e}")
    line("   รัน: python -m pip install MetaTrader5   (ถ้ายังไม่ได้ ให้ใช้ Python 3.12 แทน)")
    sys.exit(1)

# หา MT5 ที่เปิดอยู่
r = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object { \"$($_.Id)|$($_.Path)\" }"],
                   capture_output=True, text=True)
procs = []
for ln in r.stdout.splitlines():
    if "|" in ln:
        pid, path = ln.strip().split("|", 1)
        procs.append((pid, path.strip()))

line()
if not procs:
    line("❌ ไม่พบโปรแกรม MT5 (terminal64.exe) ที่เปิดอยู่")
    line("   เปิด MT5 ด้วยการดับเบิลคลิกปกติ (ไม่ใช่ Run as administrator) ล็อกอินบัญชี Demo แล้วรันไฟล์นี้ใหม่")
    sys.exit(1)

line(f"พบ MT5 เปิดอยู่ {len(procs)} ตัว:")
hidden = False
for pid, path in procs:
    if path:
        line(f"   - {path}")
    else:
        hidden = True
        line(f"   - (process {pid}) อ่านที่อยู่ไม่ได้")
if hidden and not is_admin:
    line()
    line("❌ น่าจะเป็นสาเหตุ: MT5 ถูกเปิดแบบ Administrator แต่หน้าต่างนี้ไม่ใช่ จึงคุยกันไม่ได้")
    line("   ปิด MT5 ทั้งหมด แล้วเปิดใหม่ด้วยการดับเบิลคลิกปกติ (อย่าใช้ Run as administrator)")
    line("   และตรวจว่าไม่ได้ตั้ง 'Run this program as an administrator' ไว้ในคลิกขวา > Properties > Compatibility")
if len([p for p in procs if p[1]]) > 1:
    line("⚠ มี MT5 เปิดอยู่หลายตัว ควรปิดตัวที่ไม่ใช้ หรือระบุ terminal_path ใน config.toml")

# ลองเชื่อมต่อทีละตัว
ok_path = None
for pid, path in procs:
    if not path:
        continue
    for portable in (False, True):
        line()
        line(f"ลองเชื่อมต่อ: {path}{' (portable)' if portable else ''} ... รอสูงสุด 30 วินาที")
        try:
            ok = mt5.initialize(path=path, timeout=30000, portable=portable)
        except TypeError:
            ok = mt5.initialize(path=path)
        if ok:
            ai, ti = mt5.account_info(), mt5.terminal_info()
            line("✅ เชื่อมต่อได้แล้ว")
            if ai:
                line(f"   บัญชี {ai.login} โบรกเกอร์ {ai.server} ยอดเงิน {ai.balance:,.2f} {ai.currency}")
            else:
                line("   ⚠ ยังไม่ได้ล็อกอินบัญชีใน MT5 ตัวนี้ ให้ล็อกอินก่อน")
            if ti:
                line(f"   Algo Trading: {'เปิด' if ti.trade_allowed else 'ปิด (กดปุ่ม Algo Trading ใน MT5 ให้เป็นสีเขียว)'}")
            mt5.shutdown()
            ok_path = (path, portable)
            break
        line(f"   ไม่ได้: {mt5.last_error()}")
    if ok_path:
        break

line()
if ok_path:
    path, portable = ok_path
    line("=== วิธีแก้ ===")
    line("เปิด config.toml แล้วแก้บรรทัด terminal_path ในหมวด [account] เป็น:")
    line(f'terminal_path = "{path.replace(chr(92), "/")}"')
    if portable:
        line("(MT5 ตัวนี้ติดตั้งแบบ portable: แจ้งผู้พัฒนาให้เปิดตัวเลือก portable ใน run_live.py)")
    line("บันทึกไฟล์ แล้วรัน python run_live.py ใหม่")
else:
    line("❌ ยังเชื่อมต่อไม่ได้ ลองตามนี้:")
    line("   1. ปิด MT5 ทั้งหมด (ดูใน Task Manager ว่าไม่มี terminal64 ค้าง) แล้วเปิดใหม่แบบปกติ ล็อกอิน รอจนเชื่อมต่อ")
    line("   2. ใน MT5: Help > Check for updates ให้เป็นรุ่นล่าสุด")
    line("   3. ถ้าใช้ Python 3.13/3.14 ให้ติดตั้ง Python 3.12 (64-bit) แล้ว python -m pip install -r requirements.txt")
    line("   4. ส่งผลทั้งหมดของหน้าจอนี้ให้ผู้ช่วยดู")
