#!/usr/bin/env python3

import pickle
import os
import re
import requests
import subprocess
import sys
import time
import traceback
from datetime import date

from common import setup_log
import settings


LOG = setup_log("alenkabot", settings.LOG_FILE)


class APIError(Exception):

    def __init__(self, msg):

        Exception.__init__(self, msg)


class AlenkaActions:

    commands = {
        "uptime": "время работы моего сервера",
        "start": "приветственное сообщение",
        "help": "список всех команд"
    }

    def __exec(self, command):
        proc = subprocess.Popen(command, stdout=subprocess.PIPE)

        return proc.stdout.read().strip().decode("utf-8")

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


class Alenka:

    def __init__(self, token, allowed_ids=[]):

        self.tapi = settings.TELEGRAM_API_URL
        self.token = settings.TOKEN
        self.updates_file = settings.UPDATES_FILE
        self.allowed_chats = allowed_ids
        self.last = self._get_last()

        self.actions = AlenkaActions()
        self.allowed_actions = self.actions.commands.keys()

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

        if self.allowed_chats and (message["from"]["id"] not in self.allowed_chats):
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

    alenka = Alenka(settings.TOKEN, allowed_ids=settings.ALLOWED_IDS)
    alenka.event_loop()
