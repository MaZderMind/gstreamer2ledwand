#!/usr/bin/python3

import sys, os
import struct
import socket
import json
from select import select
from time import sleep
from itertools import count as cnt
from binascii import crc32

default_cb = ""

def s2h(s):
    return " ".join([hex(struct.unpack("<B", i)[0]) for i in s])

PT = {
  0x00 :{ "name" : "DATA",
          "format" : struct.Struct("<BBHH"), # pt, group, offset, len
        },
  0x02 :{ "name" : "PICDATA",
          "format" : struct.Struct("<BBBHH"), # pt, slot, error, offset, len
        },
  0x10 :{ "name" : "FLUSH",
          "format" : struct.Struct("<BB"), # pt, group
        },
  0x80 :{ "name" : "CONFIG_R",
          "format" : struct.Struct("<BBBB"), # pt, offset, len, error
        },
  0x82 :{ "name" : "CONFIG_W",
          "format" : struct.Struct("<BBBB"), # pt, offset, len, error
        },
  0xF0 :{ "name" : "FLASH_WRITE",
          "format" : struct.Struct("<BBBBL"), # pt, [offset, len, error] "signature": 0xCBBCABBA
        },
  0xF2 :{ "name" : "FIRMWARE_UPDATE_INIT",
          "format" : struct.Struct("<BBLL"), # pt, error, number of pages, length_last_page
        },
  0xF4 :{ "name" : "FIRMWARE_SEND_PAGE",
          "format" : struct.Struct("<BBLL"), # pt, error, page_no, page_checksum
        },
  0xF6 :{ "name" : "FIRMWARE_UPDATE_FINALIZE",
          "format" : struct.Struct("<BBLL"), # pt, error, page_count, page_checksums_checksum
        },
}

CONFIG = {
  0x01 :{ "name" : "GROUP",
          "format" : struct.Struct("<B"),
        },
  0x02 :{ "name" : "ID",
          "format" : struct.Struct("<B"),
        },
  0x03 :{ "name" : "DMX_addr",
          "format" : struct.Struct("<H"),
        },
  0x04 :{ "name" : "DMX_swap",
          "format" : struct.Struct("<B"),
          "values" : {
            0x00 : "don't swap DMX pins",
            0x01 : "swap DMX pins",
          }
        },
  0x05 :{ "name" : "MODE",
          "format" : struct.Struct("<BBB"), # primary, secondary, buffer
          "primary" : {
            0x00 : "Network",
            0x01 : "DMX",
            0x02 : "static",
          },
          "secondary" : { 0x00 : "todo!" },
          "buffer" : {
            0x00 : "no Double Buffering",
            0x01 : "Double Buffering enabled",
          },
        },
  0x08 :{ "name" : "DEBUG",
          "format" : struct.Struct("<B"),
          "values" : "currently, only software override",
        },
  0x10 :{ "name" : "NET_TIMEOUT",
          "format" : struct.Struct("<HH"),
          "values" : "timeout, return in seconds"
        },
}

class LedCtrl:
  DATA_HEADER = b"\x00\x00" # followed by 16-bit len, 16-bit offset
  FLUSH_HEADER = b"\x10\x00"
  def __init__(self, blocksize=350*3, dport=5656, base_address="192.168.10.", bcast_offset="255", auto_flush="single", timeout=2):
    self.flush=auto_flush
    self.blocksize = blocksize
    self.dport = dport
    self.base_address = base_address
    self.bcast_offset = bcast_offset
    self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.timeout = timeout
    self.sock.bind(("0.0.0.0", 5657)) #test

  def flush_all(self):
    packet = LedCtrl.FLUSH_HEADER
    self.sock.sendto(packet, (self.base_address+self.bcast_offset, self.dport))
    #time.sleep(0.1)

  def flush_single(self, id):
    packet = LedCtrl.FLUSH_HEADER
    self.sock.sendto(packet, (self.base_address+str(100+id), self.dport))

  def auto_flush(self, id):
    if self.flush == "all":
      self.flush_all()
    elif self.flush == "single":
      self.flush_single(id)
    elif self.flush == "none":
      pass
    else:
      print("WARN: unrecognized auto_flush value!")

  def clear(self, id):
    self.send_frame(id, "".join(["\x00" for i in range(1024*3)]))

  def send_frame(self, id, data):
    if len(data) != 1024*3:
      print("WARN: len(data) = %d != 3072, padding/truncating!" % len(data))
      data = data[:3072]
    offset = 0
    while data:
      buf = data[:self.blocksize]
      packet = LedCtrl.DATA_HEADER
      packet += struct.pack("<H", int(len(buf)/3))
      packet += struct.pack("<H", int(offset))
      packet += buf
      self.sock.sendto(packet, (self.base_address+str(100+id), self.dport))
      offset += self.blocksize/3
      data = data[self.blocksize:]
    self.auto_flush(id)

  def send_picframe(self, id, slot, data, retries=2):
    if len(data) != 1024*3:
      print("ERROR: len(data) = {} != 3072!".format(len(data)))
      return None
    if 0 > slot > 14:
      print("ERROR: slot {} out of range!".format(slot))
      return None
    offset = 0
    pt = 0x02
    error = 0xCB
    while data:
      buf = data[:self.blocksize]
      length = len(buf)/3
      print(" ".join([hex(i) for i in [pt, slot, error, offset, length]]))
      packet = "".join([PT[pt]["format"].pack(pt, slot, error, offset, length), buf])
      success = False
      for i in range(retries):
        ret = self._send_query(id, packet)
        sleep(2)
        if ret is not None:
          header = PT[pt]["format"].unpack(ret[:PT[pt]["format"].size])
          if header[0] == 0x03 and header[2] == 0x00:
            success = True
          else:
            print("ERROR: {}".format(s2h(data)))
      if success:
        offset += self.blocksize/3
        data = data[self.blocksize:]
      else:
        print("sending failed, aborting!")
        return None
    return True

  def update_firmware(self, id, data):
    of = open("crcs.txt", "w")
    error = 0
    pages = [ data[i:i+256] for i in range(0, len(data), 256) ]
    i = struct.pack("<L", 0)
    checksums = [ crc32("".join([struct.pack("<L", i), page]), 0xFFFFFFFF)&0xFFFFFFFF for i, page in enumerate(pages) ]
    ccs = []
    for c in checksums:
      ccs.append(crc32("".join([struct.pack("<L", c)]), 0xFFFFFFFF)&0xFFFFFFFF)
    checksums_checksum = crc32("".join([struct.pack("<L", c) for c in checksums]), 0xFFFFFFFF)&0xFFFFFFFF
    #print([s2h(page) for page in pages], [hex(c) for c in checksums], hex(checksums_checksum))
    for i in range(len(ccs)):
      of.write("{} {} {}\n".format(i, hex(checksums[i]), hex(ccs[i])))
    # send init packet
    pt = 0xF2
    ret = self._send_query(id, PT[pt]["format"].pack(pt, 0, len(pages), len(pages[-1])))
    if not ret or ret[1] != "\x00":
      # error
      print("init Error!")
      if ret:
        print(s2h(ret))
      return False
    # send dataz
    pt = 0xF4
    i = 0
    while i < len(pages):
      #print(i,)
      page = pages[i]
      ret = self._send_query(id, "".join([PT[pt]["format"].pack(pt, 0, i, checksums[i]),page]))
      if not ret or ret[1] != "\x00":
        # error
        print("data Error!")
        if ret:
          print(s2h(ret))
          if ret[1] == "\x12": # requested retransmit
            i = struct.unpack("<L", ret[2:2+4])[0]
            print("resending %d..." % i)
            continue
        return False
      i += 1
    # finish up
    pt = 0xF6
    print(hex(checksums_checksum))
    ret = self._send_query(id, PT[pt]["format"].pack(pt, 0, len(pages), checksums_checksum), 20)
    if not ret or ret[1] != "\x00":
      # error
      print("finalize Error!: {}".format(s2h(ret)))
      return False
    return True

  def _send_query(self, id, data, timeout=None):
    #sleep(0.1)
    # send to brick and return response or None if select times out
    #print("trying to send to {}:\n {}\n".format(id, s2h(data)))
    if timeout == None:
      timeout = self.timeout
    self.sock.sendto(data, (self.base_address+str(100+id), self.dport))
    r, w, e = select([self.sock], [], [], timeout)
    if r:
      d = r[0].recv(1024)
      #print("got: {}".format(s2h(d)))
      return d
    else:
      return None


  def config_read(self, id, config_index):
    try:
      config_info = CONFIG[config_index]
    except KeyError:
      print("Invalid config index! Possible Values:")
      print([hex(i) for i in CONFIG.keys()])
      return None
    pt = 0x80
    offset = config_index
    length = config_info["format"].size
    error = 0
    packet = PT[pt]["format"].pack(pt, offset, length, error)
    print(s2h(packet))
    data = self._send_query(id, packet)
    if data is not None:
      header = PT[pt]["format"].unpack(data[:PT[pt]["format"].size])
      vals = data[PT[pt]["format"].size:PT[pt]["format"].size + length]
      if len(vals) != config_info["format"].size:
        print("Error: not enough data to unpack: {}".format(s2h(vals)))
        return None
      values = config_info["format"].unpack(vals)
      return header, values
    else:
      print("timeout!")
      return None

  def config_write(self, id, config_index, values):
    try:
      config_info = CONFIG[config_index]
    except KeyError:
      print("Invalid config index! Possible Values:")
      print([hex(i) for i in CONFIG.keys()])
      return None
    pt = 0x82
    offset = config_index
    length = config_info["format"].size
    error = 0
    packet = PT[pt]["format"].pack(pt, offset, length, error)
    try:
      data = config_info["format"].pack(*values)
    except struct.error:
      print("cannot pack {} into {}!".format(values, config_info["format"].format))
      return None
    packet = "".join([packet, data])
    print(s2h(packet))
    data = self._send_query(id, packet)
    if data is not None:
      try:
        header = PT[pt]["format"].unpack(data[:PT[pt]["format"].size])
        values = config_info["format"].unpack(data[PT[pt]["format"].size:PT[pt]["format"].size + length])
      except struct.error:
        print("Error parsing packet: {}".format(s2h(data)))
        return None
      return header, values
    else:
      print("timeout!")
      return None

  def write_flash(self, id):
    pt = 0xF0
    offset = 0
    length = 4
    error = 0
    sig = 0xCBBCABBA
    packet = PT[pt]["format"].pack(pt, offset, length, error, sig)
    print(s2h(packet))
    data = self._send_query(id, packet)
    if data is not None:
      print("flash ret: {}".format(s2h(data)))
      return data
    else:
      print("timeout!")
      return None





if __name__ == "__main__":
  lc = LedCtrl()
  lc.send_frame(2, b"\x20\x20\x20"*1024)
  exit(1)

  #test = "\x00\x99\xAA\x5a"
  #lc = LedCtrl(base_address="127.0.0.")
  #print(lc.update_firmware(1, "\xFF"*1023))
  #lc.config_write(1, 0x10, (0,0))
  #lc.config_write(1, 0x08, (0,))
  #print(lc.config_read(0, 0x10))
  # set IP and write
  #lc.config_write(0, 0x02, (1,))
  sleep(2)
  #lc.config_write(0, 0x08, (1,))
  #ret = lc.config_read(0, 0x02)
  #if ret:
  #  print(ret)
  #  lc.write_flash(0)
  #else:
  #  print("Error! not flashing...")
