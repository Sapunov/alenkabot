#!/usr/bin/env python
# -*- coding: UTF-8 -*-

from signal import SIGTERM
import atexit
import cPickle as pickle
import logging
import os
import re
import requests
import subprocess
import sys
import time
import traceback
from datetime import date


reload(sys)
sys.setdefaultencoding("utf-8")

APP = __file__.split("/")[-1].split(".")[0]

logging.basicConfig(
    datefmt="%d.%m.%y_%H:%M:%S",
    format=u"%(asctime)s.%(msecs)03d %(filename)15.15s:%(lineno)-3d %(levelname)-8s : %(message)s",
    filename="/var/log/{}.log".format(APP))

LOG = logging.getLogger(APP)
LOG.setLevel(logging.DEBUG)


class APIError(Exception):
    def __init__(self, msg):
        Exception.__init__(self, msg)


class Daemon(object):
    def __init__(self, stdin="/dev/null",
                 stdout="/dev/null", stderr="/dev/null"):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr

    def daemonize(self):
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError, e:
            sys.stderr.write("fork #1 failed: %d (%s)\n" % (
                e.errno, e.strerror))
            sys.exit(1)

        os.chdir("/")
        os.setsid()
        os.umask(0)

        try:
            pid = os.fork()
            if pid > 0:
                print "Starting daemon with pid {0}".format(pid)
                sys.exit(0)
        except OSError, e:
            sys.stderr.write("fork #2 failed: %d (%s)\n" % (
                e.errno, e.strerror))
            sys.exit(1)

        sys.stdout.flush()
        sys.stderr.flush()
        si = file(self.stdin, "r")
        so = file(self.stdout, "a+")
        se = file(self.stderr, "a+", 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

        atexit.register(self.delpid)
        pid = str(os.getpid())
        file(self.pidfile, "w+").write("%s\n" % pid)

    def delpid(self):
        os.remove(self.pidfile)

    def start(self):
        LOG.info("Daemon start")
        try:
            pf = file(self.pidfile, "r")
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None

        if pid:
            message = "pidfile %s already exist. Daemon already running?\n"
            sys.stderr.write(message % self.pidfile)
            sys.exit(1)

        self.daemonize()
        self.event_loop()

    def stop(self):
        LOG.info("Daemon stop")
        try:
            pf = file(self.pidfile, "r")
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None

        if not pid:
            message = "pidfile %s does not exist. Daemon not running?\n"
            sys.stderr.write(message % self.pidfile)
            return

        try:
            while 1:
                os.kill(pid, SIGTERM)
                time.sleep(0.1)
        except OSError, err:
            err = str(err)
            if err.find("No such process") > 0:
                if os.path.exists(self.pidfile):
                    os.remove(self.pidfile)
            else:
                print str(err)
                sys.exit(1)

    def restart(self):
        LOG.info("Daemon restart")
        self.stop()
        self.start()

    def event_loop(self):
        pass


class AlenkaActions(object):
    commands = {
        "uptime": "время работы моего сервера",
        "vkonline": "сколько ты сегодня сидишь в ВК",
        "start": "приветственное сообщение",
        "help": "список всех команд"
    }

    def __exec(self, command):
        proc = subprocess.Popen(command, stdout=subprocess.PIPE)

        return proc.stdout.read().strip()

    def _unauthorized(self, **kwargs):
        LOG.info("Unauthorized access.")
        return "Мама велела не разговаривать с незнакомцами."

    def _undefined(self, **kwargs):
        LOG.info("Undefined method.")
        return "Я пока не знаю таких слов."

    def _textonly(self, **kwargs):
        return "Я пока работаю только с текстом."

    def uptime(self, **kwargs):
        hostname = self.__exec(["hostname"])
        return "Сервер " + hostname + " " + self.__exec(["uptime", "-p"])

    def start(self, **kwargs):
        return "Привет! Я бот Алёнка.\n\nНабери /help чтобы узнать все мои возможности."

    def help(self, **kwargs):
        message = "Мои команды:" + "\n\n"
        for key in self.commands:
            message += "/{0} - {1}\n".format(key, self.commands[key])

        return message

    def vkonline(self, **kwargs):
        vklog = "/opt/vkonline/datafile"

        uids = {3571087: 35541806, 199141772: 17538120}

        count = 0
        td = date.today().timetuple()
        with open(vklog) as fid:
            for line in fid.readlines():
                if re.search("{0}-{1}-{2}".format(td[0], td[1], td[2]), line):
                    if re.search(str(uids[kwargs["uid"]]), line):
                        count += int(line.split(";")[2])

        return "Сегодня ты сидишь в ВК уже " + str(round(count / 60.0, 3)) + "ч."


class Alenka(Daemon):
    def __init__(self, token, allowed_ids=[]):
        self.tapi = "https://api.telegram.org/bot{0}/{1}"
        self.token = token
        self.updates_file = "/var/lib/{0}/{0}.data".format(APP)
        self.allowed_chats = allowed_ids
        self.last = self._get_last()

        self.actions = AlenkaActions()
        self.allowed_actions = self.actions.commands.keys()

        self.pidfile = "/var/run/{}.pid".format(APP)

        super(Alenka, self).__init__()

        LOG.debug(
            "Alenka initialized with: allowed_chats[{0}] and allowed_actions[{1}]. Offset = {2}".format(
                self.allowed_chats, self.allowed_actions, self.last)
        )

    def _get_last(self):
        if os.path.exists(self.updates_file):
            try:
                with open(self.updates_file, "rb") as fid:
                    return pickle.load(fid)
            except Exception as e:
                LOG.error(e)
        else:
            return 0

    def _save_last(self):
        try:
            with open(self.updates_file, "wb") as fid:
                pickle.dump(self.last, fid)
                LOG.debug("Updates saved on hard disk: {0}".format(
                    self.updates_file)
                )
        except Exception as e:
            LOG.error(e)

    def query(self, method, params={}):
        LOG.info("Make request: method={0}, params={1}".format(
            method, params))
        req = requests.get(self.tapi.format(self.token, method), params=params)

        answer = req.json()

        if answer["ok"]:
            return answer["result"]
        else:
            raise APIError(answer)

    def _get_answer(self, command, uid=None, other=[]):
        if len(other) > 0:
            return getattr(self.actions, command)(uid=uid, other=other)
        else:
            return getattr(self.actions, command)(uid=uid)

    def get_answer(self, message):
        LOG.info("Get message: {0}.".format(message))

        if message["from"]["id"] not in self.allowed_chats:
            return self._get_answer("_unauthorized")

        if "text" not in message:
            return self._get_answer("_undefined")

        words = re.findall(r"(\w+)", message["text"], re.UNICODE)
        words = [word.lower() for word in words]

        LOG.debug("Words: {0}".format(words))

        if words[0] not in self.allowed_actions:
            return self._get_answer("_undefined")
        else:
            return self._get_answer(words[0], message["from"]["id"], other=words[1:])

    def event_loop(self):
        timeout = 1
        empty_count = 0
        max_timeout = 5

        LOG.debug("Alenka started")

        while True:
            try:
                ans = self.query("getUpdates", params={"offset": self.last + 1})
                if len(ans) > 0:
                    timeout = 1
                    for u in ans:
                        self.query(
                            "sendMessage", params={
                                "chat_id": u["message"]["chat"]["id"],
                                "text": self.get_answer(u["message"])}
                        )
                        self.last = max([self.last, u["update_id"]])
                    self._save_last()
                else:
                    empty_count += 1
                    if empty_count >= 10:
                        if timeout < max_timeout:
                            timeout += 2
                            empty_count = 0

                time.sleep(timeout)
            except Exception:
                self._save_last()
                LOG.error(traceback.format_exc())


if __name__ == "__main__":
    with open("token") as fid:
        token = fid.read().strip()

    alenka = Alenka(token, allowed_ids=[3571087, 17538120])

    if len(sys.argv) == 2:
        if "start" == sys.argv[1]:
            alenka.start()
        elif "stop" == sys.argv[1]:
            alenka.stop()
        elif "restart" == sys.argv[1]:
            alenka.restart()
        else:
            print "Unknown command"
            sys.exit(2)
        sys.exit(0)
    else:
        print "usage: %s start | stop | restart" % sys.argv[0]
        sys.exit(2)
