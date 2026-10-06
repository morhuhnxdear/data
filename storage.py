import csv
import json
import os
import time


class Storage:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.p_state = os.path.join(folder, "state.json")
        self.p_trades = os.path.join(folder, "trades.csv")
        self.p_days = os.path.join(folder, "days.csv")
        self.p_strat = os.path.join(folder, "strategies.json")
        self.p_signals = os.path.join(folder, "signals.csv")

    def _append_csv(self, path, row):
        new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if new:
                w.writeheader()
            w.writerow(row)

    def log_trade(self, row):
        self._append_csv(self.p_trades, row)

    def log_signal(self, row):
        """จุดแนะนำเข้าซื้อขาย 1 แถวต่อ 1 จุด เขียนเมื่อรู้ผลแล้ว (ถึง TP / โดน SL / หมดเวลา)"""
        self._append_csv(self.p_signals, row)

    def log_day(self, row):
        self._append_csv(self.p_days, row)

    def save_state(self, state):
        """บันทึกแบบปลอดภัย: เขียนไฟล์ชั่วคราวก่อนแล้วสลับ ถ้าไฟล์ถูกโปรแกรมอื่นเปิดอยู่ชั่วขณะ
        (เช่น แดชบอร์ดกำลังอ่าน หรือโปรแกรมสแกนไวรัส) จะลองใหม่หลายครั้ง คืนค่า False ถ้ายังไม่สำเร็จ"""
        tmp = self.p_state + ".tmp"
        data = json.dumps(state, ensure_ascii=False)
        for i in range(10):
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(data)
                os.replace(tmp, self.p_state)
                return True
            except PermissionError:
                time.sleep(0.05 + 0.02 * i)      # รอรวมสูงสุดประมาณ 1.5 วินาที แล้วข้ามรอบนี้
        return False

    def load_state(self):
        if not os.path.exists(self.p_state):
            return None
        with open(self.p_state, encoding="utf-8") as f:
            return json.load(f)

    def load_strategies(self):
        if not os.path.exists(self.p_strat):
            return []
        with open(self.p_strat, encoding="utf-8") as f:
            return json.load(f)

    def save_strategy(self, doc):
        items = self.load_strategies()
        items.append(doc)
        with open(self.p_strat, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
