#!/usr/bin/python3

import ledcontrol, png

if __name__ == "__main__":
  lc = ledcontrol.LedCtrl()
  r = png.Reader('voc-inv.png')
  (w, h, px, meta) = r.read_flat()

  if w != 32 or h != 32:
    print("w and h must be 32")
    sys.exit(1)

  if len(px) != 32*32*3:
    print("color-mode must be RGB")
    sys.exit(1)

  lc.send_frame(2, px)
  exit(0)

