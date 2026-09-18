#!/usr/bin/env python3
from __future__ import annotations
import socket
from pathlib import Path

HOST="127.0.0.1"
PORT=2345

FIRST_CTRL=0x800F6670
FIRST_PTR=0x800A666C
FIRST_STATE=FIRST_PTR+0x291
FIRST_ALLOWED={0x04,0x06}

SECOND_CTRL=0x800F65F0
SECOND_PTR=0x800B5170
SECOND_STATE=SECOND_PTR+0x291
SECOND_ALLOWED={0x04}

OUT="mizzurna_one_click_rescue_v33.txt"

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
            p+=b
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
        try:
            self.s.close()
        except:
            pass

def u32(b,o=0):
    return int.from_bytes(b[o:o+4],"little")

def inspect(r):
    c1=r.mem(FIRST_CTRL,0x20)
    c2=r.mem(SECOND_CTRL,0x20)
    return {
        "p1":u32(c1,0x14),
        "s1":r.mem(FIRST_STATE,1)[0],
        "p2":u32(c2,0x14),
        "s2":r.mem(SECOND_STATE,1)[0],
    }

def main():
    lines=[
        "MIZZURNA FALLS ONE-CLICK SOFTLOCK RESCUE v33",
        "="*92
    ]

    try:
        r=RSP()
    except Exception as e:
        lines.append(f"CONNECT ERROR: {type(e).__name__}: {e}")
        Path(OUT).write_text("\n".join(lines),encoding="utf-8")
        return 1

    try:
        st=inspect(r)
        lines += [
            f"first controller ptr=0x{st['p1']:08X}, state=0x{st['s1']:02X}",
            f"second controller ptr=0x{st['p2']:08X}, state=0x{st['s2']:02X}",
        ]

        target=None

        if st["p1"]==FIRST_PTR and st["s1"] in FIRST_ALLOWED:
            target=("FIRST / post-Bone softlock", FIRST_STATE, st["s1"])
        elif st["p2"]==SECOND_PTR and st["s2"] in SECOND_ALLOWED:
            target=("SECOND / control-return softlock", SECOND_STATE, st["s2"])

        if target is None:
            lines.append("NO KNOWN SOFTLOCK SIGNATURE. Nothing changed.")
            try:
                r.cont()
            except:
                pass
            return 2

        name,addr,old=target
        lines += [
            f"Detected: {name}",
            f"Reset address: 0x{addr:08X}",
            f"Before: 0x{old:02X}",
        ]

        r.write(addr,b"\x00")
        verify=r.mem(addr,1)[0]
        lines.append(f"Immediately after write: 0x{verify:02X}")

        try:
            r.cont()
        except:
            pass

        lines.append("RESCUE APPLIED AND GAME RESUMED.")
        return 0

    except Exception as e:
        lines.append(f"ERROR: {type(e).__name__}: {e}")
        try:
            r.cont()
        except:
            pass
        return 1

    finally:
        r.close()
        Path(OUT).write_text("\n".join(lines),encoding="utf-8")

if __name__=="__main__":
    raise SystemExit(main())
