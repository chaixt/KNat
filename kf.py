#!/usr/bin/python
# -*- coding: utf-8 -*- 

import socket;
import sys;
import select;
import threading;
import time;
import Queue;
import struct;

buf_size = 4096;


class CmdBase:
	def __init__(self):
		self.cmd = 0;
		self.body = "";

	def  setCmd(self, cmd):
		self.cmd = cmd;
		return self;

	def setBody(self, body):
		if body and hasattr(body, "dump") and callable(body.dump):
			body = body.dump();
		self.body = body;
		return self;

	def load(self, cmdinfo):
		(plen, self.cmd, self.body) = struct.unpack("=2i%ds"%(len(cmdinfo) - 8), cmdinfo);
		return self;
	def dump(self):
		return struct.pack("=2i%ds"%len(self.body), len(self.body) + 8, self.cmd, self.body);

class CmdForward:
	def __init__(self):
		self.stag = "";
		self.host = "";
		self.port = 0;
		self.data = "";

	def setSTag(self, stag):
		self.stag = stag;
		return self;

	def setHost(self, host):
		self.host = host;
		return self;

	def setPort(self, port):
		self.port = port;
		return self;

	def setData(self, data):
		self.data = data;
		return self;

	def load(self, cmdinfo):
		(tlen,) = struct.unpack("h", cmdinfo[0:2]);
		cmdinfo = cmdinfo[2:];
		(self.stag,) = struct.unpack("=%ds"%tlen, cmdinfo[0 : tlen]);
		cmdinfo=cmdinfo[tlen:];
		(tlen,) = struct.unpack("h", cmdinfo[0:2]);
		cmdinfo = cmdinfo[2:];
		(self.host, self.port) = struct.unpack("=%dsH"%tlen, cmdinfo[0 : tlen + 2]);
		cmdinfo=cmdinfo[tlen + 2:];

		(tlen,) = struct.unpack("h", cmdinfo[0:2]);
		cmdinfo = cmdinfo[2:];
		(self.data,) = struct.unpack("=%ds"%tlen, cmdinfo[0 : tlen]);
		return self;

	def dump(self):
		return struct.pack("=h%dsh%dsHh%ds"%(len(self.stag), len(self.host), len(self.data)), len(self.stag), self.stag, len(self.host), self.host, self.port, len(self.data), self.data);

class IpPort:
	def __init__(self):
		self.ip = "";
		self.port = 0;

	def setIp(self, ip):
		self.ip = ip;
		return self;

	def setPort(self, port):
		self.port = port;
		return self;

	def load(self, cmdinfo):
		(tlen,) = struct.unpack("h", cmdinfo[0:2]);
		cmdinfo = cmdinfo[2:];
		(self.ip, self.port) = struct.unpack("=%dsH"%tlen, cmdinfo[0 : tlen + 2]);
		
		return self;
	def dump(self):
		print self.ip, self.port;
		return struct.pack("=h%dsH"%len(self.ip), len(self.ip), self.ip, self.port);

CMD_FORWARD = 1;


class ServerThread(threading.Thread):
	def __init__(self, host, port):
		threading.Thread.__init__(self);
		self.host = host;
		self.port = port;
		self.send_queue = Queue.Queue();
		self.sock = False;
		self.last_buf = "";
		self.lock = threading.Lock();

	def init_sock(self):
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM);
		self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1);

	def connect(self):
		if not self.sock:
			self.init_sock();
		self.sock.connect((self.host, self.port));

	def send_obj(self, obj):
		return self.send_cmd(CMD_FORWARD, obj);


	def send_cmd(self, cmd, obj):
		if not self.sock:
			self.connect();
		self.send_queue.put_nowait(CmdBase().setCmd(cmd).setBody(obj).dump());
		return self;


	def recv_cmd(self):
		with self.lock:
			buf = self.last_buf;
			self.last_buf = "";
			while(True):
				try:
					buf += self.sock.recv(buf_size);
					if len(buf) >= 4:
						(l,) = struct.unpack("i", buf[0:4]);
						if len(buf) > l:
							self.last_buf = buf[l:];
							buf=buf[0:l];
							break;
						if len(buf) == l:
							break;
				except socket.timeout,e:
					continue;
			if buf != None and len(buf) > 0:
				return CmdBase().load(buf);

	def run(self):
		try:
			while(True):
				cmd = self.send_queue.get();
				if cmd is None:
					break;
				self.sock.send(cmd);
		except Exception,e:
			print e;
			print "disconnect from server";
			sys.exit(0);
		
		
class NatThread(threading.Thread):
	def __init__(self, src_tag, host, port, send_func):
		threading.Thread.__init__(self);
		self.srct = src_tag;
		self.host = host;
		self.port = port;
		self.sock = False;
		self.send_func = send_func;

	def init_sock(self):
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM);
		self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1);

	def connect(self):
		if not self.sock:
			self.init_sock();
		self.sock.connect((self.host, self.port));

	def send(self, msg):
		if not self.sock:
			self.connect();
		if len(msg) > 0:
			self.sock.send(msg);


	def run(self):
		try:
			while(True):
				sbuf = self.sock.recv(buf_size);
				if sbuf == None or len(sbuf) <= 0:
					self.sock.close();
					break;
#				print sbuf;
				print "Send:", len(sbuf);
				self.send_func(CmdForward().setSTag(self.srct).setHost(self.host).setPort(self.port).setData(sbuf));
		except Exception,e:
			print "------------------"
			print e;
			print "disconnect from nat";
			sys.exit(0);

if __name__ == '__main__':
	host = sys.argv[1];
	port = int(sys.argv[2]);

	forward_map = {};

	sthread = ServerThread(host, port);
	sthread.connect();
	sthread.start();
	while True:
		cmd = sthread.recv_cmd();
		if cmd.cmd == CMD_FORWARD:
			cmd = CmdForward().load(cmd.body);
			if forward_map.has_key(cmd.stag):
#				print cmd.data;
#				print len(cmd.data);
				nthread = forward_map[cmd.stag];
				nthread.send(cmd.data);
			else:
				nthread = NatThread(cmd.stag, cmd.host, cmd.port, sthread.send_obj);
				forward_map[cmd.stag] = nthread;
				print forward_map;
				nthread.send(cmd.data);
				nthread.start();

