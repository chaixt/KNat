#!/usr/bin/python
# -*- coding: utf-8 -*- 

import socket;
import sys;
import select;
import threading;
import Queue;
import struct;
import json;

host = "";
port = 8083;
client_list=[];
client_map = {};
forward_map = {};


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
CMD_LIST = 0;

class Thread(threading.Thread):
	def __init__(self,sockfd,addr,port):
		threading.Thread.__init__(self)
		self.buf=""
		self.client_ip = addr;
		self.client_port = port;
		self.sock=sockfd;
		self.isrun = True;
		self.forward = False;
		self.tag = "%s:%d"%(self.client_ip, self.client_port)
		client_list.append(self.tag);
		client_map[self.tag] = self;
		self.sock.settimeout(5);
		self.lock = threading.Lock();
		self.last_buf = "";


	def send_cmd(self, cmd, obj):
		self.send_to(self.sock, cmd, obj);

	def send_to(self, sock, cmd, obj):
		sock.send(CmdBase().setCmd(cmd).setBody(obj).dump());

	def recv_cmd(self):
		with self.lock:
			buf = self.last_buf;
			self.lat_buf = "";
			while(self.isrun):
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
					pass;
			if self.forward:
				return buf;
			if buf != None and len(buf) > 0:
				return CmdBase().load(buf);

	def list_req(self):
		print self;
		print self.forward;
		if self.forward:
			tlist = [];
		else:
			tlist = [] + client_list;
			tlist.remove(self.tag);
		print json.dumps(tlist);
		self.send_cmd(CMD_LIST, json.dumps(tlist));
		return False;

	def forward_start(self, thread):
		self.forward = True;
		thread.forward = True;
		print self;
		print thread;

	def forward_stop(self, thread):
		print "Call Forward Stop";
		self.forward = False;
		thread.forward = False;

	def forward_mod(self, buf):
		if forward_map.has_key(self.tag):
			sthread = client_map[self.tag];
			tthread = client_map[forward_map[self.tag]];
			try:
				print sthread.forward, tthread.forward
				while sthread.forward and tthread.forward:
					if buf == None or len(buf) <= 0:
						try:
							while(self.isrun and self.forward and tthread.forward):
								try:
									buf = sthread.sock.recv(buf_size);
									break;
								except socket.timeout:
									pass;
						except Exception, e:
							print "Read:", e;
							sthread.stop();
							sthread.forward_stop(tthread);
							forward_map.pop(sthread.tag);
							forward_map.pop(tthread.tag);
							client_list.append(tthread.tag);
							break;
					if buf == None or (isinstance(buf, str) and len(buf) <= 0):
						sthread.stop();
						sthread.forward_stop(tthread);
						forward_map.pop(sthread.tag);
						forward_map.pop(tthread.tag);
						client_list.append(tthread.tag);
						print client_list;
						break;
					if not self.forward:
						return buf;
					print "[%s=>%s]"%(sthread.tag, tthread.tag), len(buf);
					try:
						tthread.sock.send(buf);
					except Exception, e:
						print "Write:", e;
						tthread.stop();
						tthread.forward_stop(sthread);
						forward_map.pop(sthread.tag);
						forward_map.pop(tthread.tag);
						client_list.append(sthread.tag);
						break;
					buf = None;
			except Exception, e:
				print e

	def forward_req(self, ipport):
		ipport = IpPort().load(ipport);
		tthread = client_map["%s:%d"%(ipport.ip, ipport.port)];
		print "start[%s=>%s]"%(self.tag, tthread.tag);
		client_list.remove(self.tag);
		client_list.remove(tthread.tag);
		forward_map[tthread.tag] = self.tag;
		forward_map[self.tag] = tthread.tag;
		print "send to client forward cmd";
		self.send_cmd(3, ipport);
		tthread.send_cmd(3, IpPort().setIp(self.client_ip).setPort(self.client_port));
		self.forward_start(tthread);



	def connect_req(self,ipport):
		ipport = IpPort().load(ipport);
		tip = ipport.ip;
		tport = ipport.port;
		s="%s:%d"%(tip, tport);
		if s in client_list:
			tsock = client_map[s].sock;
			try:
				self.send_to(tsock, 5, IpPort().setIp(self.client_ip).setPort(self.client_port));
				tsock.close();
			except:
				print s, "disconnected";
			finally:
				client_list.remove(s);
				client_map.pop(s);
				try:
					self.send_cmd(4, IpPort().setIp(tip).setPort(tport));
					self.sock.close();
				finally:
					client_list.remove(self.tag);
					client_map.pop(self.tag);
					self.stop();
			return True;
		return False;

	def stop(self):
		self.isrun = False;

	def run(self):
		try:
			self.list_req();
			while(self.isrun):
				cmdobj = self.recv_cmd();
				print cmdobj;
				if cmdobj != None or (isinstance(cmdobj, str) and len(cmdobj) > 0):
					if isinstance(cmdobj, CmdBase):
						print "Recv:CMD:", cmdobj.cmd;
						if cmdobj.cmd == 6:
							self.list_req();
						elif cmdobj.cmd == 7:
							if self.connect_req(cmdobj.body):
								break;
						elif cmdobj.cmd == 8:
							print "forward"
							self.forward_req(cmdobj.body);
						cmdobj = None;
					print self.forward;
					if self.forward:
						print "goto forward";
						cmdobj = self.forward_mod(cmdobj);
				else:
					print self.tag, "disconnected";
					break;
				cmdobj = None;
		finally:
			if self.tag in client_list:
				client_list.remove(self.tag);
				client_map.pop(self.tag);
				self.sock.close()
			print client_list;


sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM);
sock.bind((host, port));
sock.listen(10);
while 1:
	infds,outfds,errfds=select.select([sock,],[],[],5) #使用select函数进行非阻塞操作
	if len(infds)!=0:
		csock,(addr,port)=sock.accept()
		print 'connected by',addr,port
		t=Thread(csock, addr, port)
		t.start()
sock.close()