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
		self.sock.settimeout(5);

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
			if len(buf) >= 4:
				(l,) = struct.unpack("i", buf[0:4]);
				print "l=", l;
				if len(buf) > l:
					self.last_buf = buf[l:];
					buf=buf[0:l];
					return CmdBase().load(buf);
				if len(buf) == l:
					return CmdBase().load(buf);
			while(True):
				try:
					buf += self.sock.recv(buf_size);
					print "LBuf:", len(buf);
					if len(buf) >= 4:
						(l,) = struct.unpack("i", buf[0:4]);
						print "l=", l;
						if len(buf) > l:
							self.last_buf = buf[l:];
							buf=buf[0:l];
							break;
						if len(buf) == l:
							break;
				except socket.timeout,e:
					continue;
			#print buf;
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
		
class LocThread(threading.Thread):
	def __init__(self, sock, tag, host, port, send_func):
		threading.Thread.__init__(self);
		self.sock = sock;
		self.tag = tag;
		self.host = host;
		self.port = port;
		self.send_func = send_func;
		self.send_func(CmdForward().setSTag(self.tag).setHost(self.host).setPort(self.port).setData(""));


	def send(self, msg):
		(sip, sport) = self.sock.getsockname();
#		self.sock.send(msg.replace(self.host, sip));
		self.sock.send(msg);


	def run(self):
		try:
			(sip, sport) = self.sock.getsockname();
			sbuf = '';
			while(True):
				try:
					try:
						sbuf += self.sock.recv(buf_size);
#						print len(sbuf);
						if sbuf == None or len(sbuf) <= 0:
							self.sock.close();
							break;
#						print sbuf;
#						self.send_func(CmdForward().setSTag(self.tag).setHost(self.host).setPort(self.port).setData(sbuf.replace(sip, self.host)));
						self.send_func(CmdForward().setSTag(self.tag).setHost(self.host).setPort(self.port).setData(sbuf));
						sbuf = "";
					except socket.timeout,e:
						continue;
				except Exception, e:
					print e;
		except Exception,e:
			print e;
			print "disconnect from nat";
			sys.exit(0);



class ServerRecv:
	def __init__(self, sthread, port):
		self.loc_sock = None;
		self.sthread = sthread;
		self.forward_map = {};
		self.port = port;
		self.rhost = "127.0.0.1";
		self.rport = 3306


	def setRHost(self, rhost):
		self.rhost = rhost;
		return self;

	def setRPort(self, rport):
		self.rport = rport;
		return self;

	def list_rsp(self, cmdbody):
		print cmdbody;
		c = cmdbody[2:-2];
		buf = c.split(":");
		print self.sthread.sock.getsockname();
		self.sthread.send_cmd(8, IpPort().setIp(buf[0]).setPort(int(buf[1])));
		print self.sthread.sock.getsockname(), "OK";
		threading.Thread(target = self.listen).start();

	def listen(self):
		self.loc_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM);
		self.loc_sock.bind(("", self.port));
		self.loc_sock.listen(10);
		while True:
			rcv_sock,(rcv_ip, rcv_port) = self.loc_sock.accept();
			rcv_sock.settimeout(5);
			buf = rcv_sock.recv(buf_size);
			try:
				if len(buf) >= 9:
					buf = buf[2:];
					(self.rport, ) = struct.unpack("!H", buf[0:2]);
					self.rhost = socket.inet_ntoa(buf[2:6]);
					rcv_sock.send(struct.pack("2s6s", "\x00\x5A", buf[2:6]));
					tag = "%s:%d"%(rcv_ip, rcv_port);
					lthread = LocThread(rcv_sock, tag, self.rhost, self.rport, self.sthread.send_obj);
					lthread.start();
					self.forward_map[tag] = lthread;
				else:
					rcv_sock.close();
			except Exception, e:
				print e;

	def recv(self):
		while True:
			cmdobj = self.sthread.recv_cmd();
			if cmdobj != None:
#				print cmdobj.cmd;
				if 0 == cmdobj.cmd:
					self.list_rsp(cmdobj.body);
				elif CMD_FORWARD == cmdobj.cmd:
					cmd = CmdForward().load(cmdobj.body);
#					print cmd.data;
					print "Recv:", len(cmd.data);
					if self.forward_map.has_key(cmd.stag):
						lthread = self.forward_map[cmd.stag];
						lthread.send(cmd.data);
				else:
					print cmdobj.cmd;
					print cmdobj.body;
			else:
				print "disconnect from server";
				break;


if __name__ == '__main__':
	host = sys.argv[1];
	port = int(sys.argv[2]);
	llport = int(sys.argv[3]);
	sthread = ServerThread(host, port);
	sthread.connect();
	sthread.start();
	srecv = ServerRecv(sthread, llport);
	threading.Thread(target=srecv.recv).start();
	while(1):
		sbuf = raw_input("input: ");
		buf = sbuf.split(":");
		cmd = buf[0];
		if "forward" == cmd:
			sthread.send_cmd(8, IpPort().setIp(buf[1]).setPort(int(buf[2])));
			threading.Thread(target = srecv.listen).start();
		elif "cmd" == cmd:
			if len(buf) > 1:
				t.cmd_req(buf[1], ":".join(buf[2:]));