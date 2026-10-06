"""รันระบบบอทเทรดทอง 50 ตัวกับ MetaTrader 5

  python run_live.py                 ใช้กับบัญชีทดลอง (Demo) เท่านั้น  <- เริ่มจากตรงนี้
  python run_live.py --allow-real    อนุญาตบัญชีเงินจริง (ต้องพิมพ์ยืนยัน)

สั่งการระหว่างรัน: พิมพ์คำสั่งลงไฟล์ data_live/commands.txt (บรรทัดละคำสั่ง) แล้วบันทึก
เช่น  status | pause 5 | jail 3 | teach 1 12 | close 7 | halt | unhalt | target 150 | minwr 85
กด Ctrl+C เพื่อหยุด (ออเดอร์ที่ค้างยังมี SL/TP ฝั่งโบรกเกอร์คุมอยู่)
"""
import argparse
import os
import sys
import time

from goldbots.arena import Arena, Bar, money
from goldbots.config import load_config
from goldbots.logsetup import setup_logging
from goldbots.mt5_executor import MT5Executor
from goldbots.notify import Notifier
from goldbots.storage import Storage


def to_bar(r, point, tick_spread=0.0):
    return Bar(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
               max(float(r["spread"]) * point, tick_spread))


def connect(mt5, cfg):
    acc = cfg["account"]
    kw = {}
    if acc.get("terminal_path"):
        kw["path"] = acc["terminal_path"]
    if acc.get("login"):
        kw.update(login=int(acc["login"]), password=acc["password"], server=acc["server"])
    return mt5.initialize(**kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--data", default="data_live", help="โฟลเดอร์เก็บสถานะ ประวัติเทรด และ log")
    ap.add_argument("--allow-real", action="store_true", help="อนุญาตให้เทรดบัญชีเงินจริง")
    ap.add_argument("--reset", action="store_true", help="ล้างสถานะเดิมแล้วคัดเลือกใหม่ทั้งหมด")
    args = ap.parse_args()

    cfg = load_config(args.config)
    log = setup_logging(os.path.join(args.data, "bot.log"))
    try:
        import MetaTrader5 as mt5
    except ImportError:
        sys.exit("ยังไม่ได้ติดตั้ง MetaTrader5: pip install MetaTrader5 (ใช้ได้บน Windows เท่านั้น)")

    if not connect(mt5, cfg):
        sys.exit(f"เชื่อมต่อ MT5 ไม่ได้: {mt5.last_error()}  (เปิดโปรแกรม MT5 และล็อกอินไว้ก่อน)")
    ai, ti = mt5.account_info(), mt5.terminal_info()
    if ai is None or ti is None:
        sys.exit("อ่านข้อมูลบัญชีไม่ได้ ตรวจว่าล็อกอินใน MT5 แล้ว")

    kind = {mt5.ACCOUNT_TRADE_MODE_DEMO: "ทดลอง (Demo)", mt5.ACCOUNT_TRADE_MODE_CONTEST: "แข่งขัน",
            mt5.ACCOUNT_TRADE_MODE_REAL: "เงินจริง"}.get(ai.trade_mode, "?")
    log("info", f"บัญชี {ai.login} ({kind}) โบรกเกอร์ {ai.server} ยอดเงิน {ai.balance:,.2f} {ai.currency}")
    if ai.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
        if not args.allow_real:
            mt5.shutdown()
            sys.exit("นี่คือบัญชีเงินจริง ระบบไม่ยอมรันถ้าไม่ใส่ --allow-real  แนะนำให้ทดสอบกับบัญชี Demo ก่อน 1-3 เดือน")
        print("\n⚠ กำลังจะเทรดด้วยเงินจริง ขาดทุนได้จริง")
        print(f"   ล็อตต่อไม้ {cfg['bots']['lot']}  ทีมสูงสุด {cfg['team']['size']} ตัว  "
              f"เพดานขาดทุนทีม {money(-cfg['team']['max_daily_loss'])}/วัน")
        if input("พิมพ์ YES (ตัวใหญ่) เพื่อยืนยัน: ").strip() != "YES":
            mt5.shutdown()
            sys.exit("ยกเลิก")
    if ai.margin_mode != getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2):
        mt5.shutdown()
        sys.exit("บัญชีนี้เป็นแบบ Netting (รวมออเดอร์ต่อสัญลักษณ์) บอทหลายตัวถือออเดอร์แยกกันไม่ได้ "
                 "ต้องเปิดบัญชีแบบ Hedging")
    if not ti.trade_allowed:
        mt5.shutdown()
        sys.exit("MT5 ยังไม่อนุญาตให้เทรดอัตโนมัติ กดปุ่ม 'Algo Trading' บนแถบเครื่องมือของ MT5 ให้เป็นสีเขียว")
    if not ai.trade_allowed:
        mt5.shutdown()
        sys.exit("บัญชีนี้ถูกปิดการเทรด (อาจล็อกอินด้วยรหัสผ่านนักลงทุน/investor password)")
    if ai.currency != "USD":
        log("warn", f"สกุลเงินบัญชีเป็น {ai.currency} เป้าและเพดานขาดทุนใน config จะถูกตีความเป็น {ai.currency}")

    ex = MT5Executor(mt5, cfg, log)
    cfg["market"]["contract_size"] = ex.contract
    if cfg["bots"]["lot"] < ex.vmin:
        sys.exit(f"ล็อตที่ตั้งไว้ ({cfg['bots']['lot']}) ต่ำกว่าล็อตขั้นต่ำของโบรกเกอร์ ({ex.vmin})")

    storage = Storage(args.data)
    notifier = Notifier(cfg, log)
    arena = Arena(cfg, log=log, notify=notifier.send, storage=storage)
    sym, tf, point = cfg["market"]["symbol"], mt5.TIMEFRAME_M1, ex.point

    rates = mt5.copy_rates_from_pos(sym, tf, 1, int(cfg["live"]["warmup_bars"]))
    if rates is None or len(rates) < 200:
        sys.exit("ดึงราคาย้อนหลังไม่ได้ เปิดกราฟ XAUUSD M1 ใน MT5 ให้โหลดข้อมูลก่อน")
    bars = [to_bar(r, point) for r in rates]

    state = None if args.reset else storage.load_state()
    if state:
        arena.load_state(state)
        arena.preload(bars)
        log("info", "โหลดสถานะเดิมแล้ว (สูตร สถิติ และทีมเดิม)")
    else:
        log("info", f"เริ่มรอบคัดเลือกกับข้อมูลย้อนหลัง {len(bars):,} แท่ง ...")
        arena.qualify(bars)
    arena.ex = ex
    ex.reconcile(arena)
    notifier.send(f"เริ่มระบบบอทเทรดทอง บัญชี {kind}\n" + arena.status_text().split("\n")[1])
    print(arena.status_text())

    save_fail = [0, 0.0]

    def save():
        """บันทึกสถานะ ถ้าบันทึกไม่ได้ชั่วคราว ข้ามรอบนี้ไป ไม่ให้โปรแกรมเทรดหยุด"""
        try:
            ok = _save()
        except OSError as e:
            ok = False
            err = e
        else:
            err = "ไฟล์ถูกโปรแกรมอื่นเปิดค้างอยู่"
        if ok:
            save_fail[0] = 0
            return
        save_fail[0] += 1
        if time.time() - save_fail[1] > 300:          # เตือนไม่เกินทุก 5 นาที
            save_fail[1] = time.time()
            log("warn", f"บันทึก state.json ไม่สำเร็จ ({err}) จะลองใหม่รอบถัดไป "
                        f"ถ้าเตือนบ่อย ให้ปิดโปรแกรมที่เปิดไฟล์ในโฟลเดอร์ {args.data} หรือยกเว้นโฟลเดอร์นี้ในโปรแกรมสแกนไวรัส")

    def _save():
        st = arena.to_state()
        a = mt5.account_info()
        st["account"] = {"login": ai.login, "server": ai.server, "mode": kind, "real": ai.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL,
                         "currency": ai.currency, "symbol": sym,
                         "balance": a.balance if a else None, "equity": a.equity if a else None}
        st["updated_at"] = time.time()
        return storage.save_state(st)

    last_time = bars[-1].time
    next_beat = 0
    cmd_path = os.path.join(args.data, "commands.txt")
    status_every = cfg["live"]["status_every_minutes"] * 60
    next_status = time.time() + status_every
    fails = 0
    save()
    log("info", "เริ่มเทรด กด Ctrl+C เพื่อหยุด  (ดูภาพ: เปิดอีกหน้าต่างแล้วรัน python dashboard.py)")
    try:
        while True:
            new = mt5.copy_rates_from_pos(sym, tf, 1, 10)
            if new is None:
                fails += 1
                log("warn", f"อ่านราคาไม่ได้ ({mt5.last_error()}) ลองเชื่อมต่อใหม่ครั้งที่ {fails}")
                if fails in (3, 30):
                    notifier.send("⚠ ระบบเชื่อมต่อ MT5 ไม่ได้ ตรวจเครื่อง/อินเทอร์เน็ต")
                mt5.shutdown()
                time.sleep(min(60, 5 * fails))
                connect(mt5, cfg)
                continue
            fails = 0
            tick = mt5.symbol_info_tick(sym)
            tsp = (tick.ask - tick.bid) if tick else 0.0
            for r in new:
                if int(r["time"]) > last_time:
                    arena.step(to_bar(r, point, tsp))
                    last_time = int(r["time"])
                    save()
                    next_beat = time.time() + 10
            if os.path.exists(cmd_path):
                with open(cmd_path, encoding="utf-8-sig") as f:
                    lines = [x.strip() for x in f if x.strip()]
                os.remove(cmd_path)
                for line in lines:
                    out = arena.command(line)
                    arena.log("cmd", f"คำสั่ง '{line}': {out}")
                    notifier.send(f"คำสั่ง '{line}'\n{out}")
                save()
            if time.time() >= next_beat:      # ส่งสัญญาณชีพให้แดชบอร์ดแม้ตลาดปิด
                save()
                next_beat = time.time() + 10
            if time.time() >= next_status:
                next_status = time.time() + status_every
                s = arena.status_text()
                log("info", "\n" + s)
                notifier.send("\n".join(s.split("\n")[:2]))
            time.sleep(1)
    except KeyboardInterrupt:
        log("info", "หยุดระบบตามคำสั่ง ออเดอร์ที่ค้างยังมี SL/TP ฝั่งโบรกเกอร์คุมอยู่")
    finally:
        try:
            save()
        except Exception:
            storage.save_state(arena.to_state())
        mt5.shutdown()


if __name__ == "__main__":
    main()
