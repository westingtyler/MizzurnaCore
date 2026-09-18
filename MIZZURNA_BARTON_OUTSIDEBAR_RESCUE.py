#!/usr/bin/env python3
from __future__ import annotations
import socket
from pathlib import Path

HOST="127.0.0.1"
PORT=2345

CTRL=0x800F6670
ACTOR=0x800A6910          # slot 14
STATE=ACTOR+0x291         # 0x800A6BA1
EXPECTED=0x06

OUT="mizzurna_father_barton_rescue_v35.txt"

class RSP:
    def __init__(self):
        self.s=socket.create_connection((HOST,PORT),timeout=3)
        self.s.settimeout(3)
    @staticmethod
    def cs(p):
        return f"{sum(p)&255:02x}".encode()
    def rb(self):
        b=self.s.recv(1)
        if not b:
            raise ConnectionError("closed")
        return b
    def ack(self):
        while True:
            b=self.rb()
            if b==b"+":
                return
            if b==b"-":
                raise RuntimeError("rejected")
    def packet(self):
        while self.rb()!=b"$":
            pass
        p=bytearray()
        while True:
            b=self.rb()
            if b==b"#":
                break
            p += b
        got=self.s.recv(2)
        if got.lower()!=self.cs(bytes(p)).lower():
            self.s.sendall(b"-")
            raise RuntimeError("checksum mismatch")
        self.s.sendall(b"+")
        return p.decode("ascii","replace")
    def send(self,x,reply=True):
        p=x.encode()
        self.s.sendall(b"$"+p+b"#"+self.cs(p))
        self.ack()
        return self.packet() if reply else None
    def mem(self,a,n):
        x=self.send(f"m{a:x},{n:x}")
        if not x or x.startswith("E"):
            raise RuntimeError(x)
        return bytes.fromhex(x)
    def write(self,a,data):
        x=self.send(f"M{a:x},{len(data):x}:{data.hex()}")
        if x!="OK":
            raise RuntimeError(f"write failed: {x}")
    def cont(self):
        self.send("c",False)
    def close(self):
        try:self.s.close()
        except:pass

def u32(b,o=0):
    return int.from_bytes(b[o:o+4],"little")

def main():
    lines=[
        "MIZZURNA FALLS FATHER BARTON SOFTLOCK RESCUE v35",
        "="*92,
        f"Controller: 0x{CTRL:08X}",
        f"Expected actor: 0x{ACTOR:08X} (slot 14)",
        f"State byte: 0x{STATE:08X}",
        f"Expected stuck value: 0x{EXPECTED:02X}",
        ""
    ]

    try:
        r=RSP()
    except Exception as e:
        lines.append(f"CONNECT ERROR: {type(e).__name__}: {e}")
        Path(OUT).write_text("\n".join(lines),encoding="utf-8")
        return 1

    try:
        ctrl=r.mem(CTRL,0x20)
        ptr=u32(ctrl,0x14)
        state=r.mem(STATE,1)[0]

        lines.append(f"Observed controller+0x14: 0x{ptr:08X}")
        lines.append(f"Observed actor+0x291: 0x{state:02X}")

        if ptr != ACTOR:
            lines.append("SAFETY ABORT: controller target does not match slot 14.")
            try:r.cont()
            except:pass
            return 2

        if state != EXPECTED:
            lines.append("SAFETY ABORT: actor state is not 0x06.")
            try:r.cont()
            except:pass
            return 2

        r.write(STATE,b"\x00")
        verify=r.mem(STATE,1)[0]
        lines.append(f"Reset applied: 0x{state:02X} -> 0x{verify:02X}")

        try:r.cont()
        except:pass

        lines.append("RESCUED AND RESUMED.")
        return 0

    except Exception as e:
        lines.append(f"ERROR: {type(e).__name__}: {e}")
        try:r.cont()
        except:pass
        return 1

    finally:
        r.close()
        Path(OUT).write_text("\n".join(lines),encoding="utf-8")

if __name__=="__main__":
    raise SystemExit(main())
