# -*- coding: UTF-8 -*-
#-----------------------------------------------------------------------------
# project     : Lisa client
# module      : lib
# file        : recorder.py
# description : Cirular buffered records, and Wit recognition
# author      : G.Dumee
#-----------------------------------------------------------------------------
# copyright   : Neotique
#-----------------------------------------------------------------------------


#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------
from lisa.client.ConfigManager import ConfigManager
from lisa.client.lib.player import Player
from collections import deque
import threading
import base64
from wit import Wit
import requests
import time
from time import sleep,time
from twisted.python import log
import urllib2
from urllib2 import Request, urlopen
from urllib import urlencode
from subprocess import call
from json import loads


#-----------------------------------------------------------------------------
# Globals
#-----------------------------------------------------------------------------
# Max silence before considering the end of the utterance
MAX_SILENCE_s = 1

# Maximum record duration in seconds
MAX_RECORD_DURATION_s = 10

# Maximum record length before keyword spot
MAX_TIME_BEFORE_KWS_s = 5


#-----------------------------------------------------------------------------
# Recorder
#-----------------------------------------------------------------------------
class Recorder(threading.Thread):
    """
    Continuous recording class.
    """
    def __init__(self, factory):
        # Init thread class
        threading.Thread.__init__(self)
        self._stopevent = threading.Event()
        self.running_state = False
        self.rec_sink = None

        self.factory = factory
        self.configuration = ConfigManager.getConfiguration()
        self.wit = Wit(self.configuration['wit_token'])
        self.wit_context = None
        self.record = {'activated' : False, 'start' : 0, 'started' : False, 'end' : 0, 'ended' : False, 'buffers' : deque({})}
        self.continuous_mode = False
        self.temp_file = "/tmp/asr_sound"

        # Start thread
        threading.Thread.start(self)

    #-----------------------------------------------------------------------------
    def setRunningState(self, state, rec_sink = None):
        self.running_state = state
        # Get app sink
        if rec_sink is not None and self.rec_sink is not rec_sink:
            self.rec_sink = rec_sink
            self.rec_sink.connect('new-buffer', self._captureAudioBuffer)

    #-----------------------------------------------------------------------------
    def stop(self):
        # Raise stop event
        self._stopevent.set()

    #-----------------------------------------------------------------------------
    def activate(self):
        """
        Called to activate current utter as a record
        """
        # Activate record
        if self.record['started'] == True:
            self.record['activated'] = True

    #-----------------------------------------------------------------------------
    def setContinuousMode(self, enabled, wit_context = None):
        """
        Called to activate continous record mode
        """
        # Activate record
        self.continuous_mode = enabled
        self.wit_context = wit_context

    #-----------------------------------------------------------------------------
    def run(self):
        """
        Recorder main loop
        """
        # Encoded format
        CONTENT_TYPE = 'audio/mpeg3'

        # Thread loop
        while not self._stopevent.isSet():
            # Test if record is ended
            if self.record['started'] == True and self.record['ended'] == False and self.record['end'] <= time():
                # If current record was not activated before end
                if self.record['activated'] == False and self.continuous_mode == False:
                    self.record['start'] = 0
                    self.record['started'] = False
                    self.record['end'] = 0
                    self.record['ended'] = False
                    self.record['activated'] = False

                    continue

                # Current record is activated and already ended
                self.record['ended'] = True

            # If current record is not activated
            if self.running_state == False or self.record['started'] == False or (self.record['activated'] == False and self.continuous_mode == False):
                sleep(.1)
                continue

            # Send activated record to Wit
            wit_e = None
            result = ""
            try:
                if self.configuration['asr'] == "ispeech":
                    for b in self._readAudioBuffer(file_mode = True):
                        pass
                    params= {}
                    params["action"] = "recognize"
                    params["apikey"] = "developerdemokeydeveloperdemokey"
                    params["freeform"] = "3"
                    params["locale"] = "fr-FR"
                    params["output"] = "json"
                    params["content-type"] = "speex"
                    params["speexmode"] = "2"
                    params["audio"] = base64.b64encode(open(self.temp_file, 'rt').read()).replace(b'\n',b'')
                    result = requests.get("http://api.ispeech.org/api/rest?" + urlencode(params))
                    result = self.wit.get_message(query = result.json()['text'], context = self.wit_context)

                elif self.configuration['asr'] == "google":
                    for b in self._readAudioBuffer(file_mode = True):
                        pass
                    url = 'https://www.google.com/speech-api/v2/recognize?output=json&lang=fr-fr&key=AIzaSyCQv4U1mTaw_r_j1bWb1peeaTihzV0q-EQ'
                    audio = open(self.temp_file, "rb").read()
                    header = {"Content-Type": "audio/x-flac; rate=16000"}
                    post = urlopen(Request(url, audio, header))
                    result = loads(post.read().split("\n")[1])['result'][0]['alternative'][0]['transcript']
                    result = self.wit.get_message(query = result, context = self.wit_context)

                # Defautl Wit
                else:
                    result = self.wit.post_speech(data = self._readAudioBuffer(), content_type = CONTENT_TYPE, context = self.wit_context)

                result['msg_body'] = result['msg_body'].encode("utf-8")
            except Exception as e:
                wit_e = e

            # If record was stopped during Wit access
            if self._stopevent.isSet():
                break

            # Question mode
            if len(result) > 0 and self.continuous_mode == True and result.has_key('msg_body') == True and len(result['msg_body']) > 0:
                # Send answer
                self.factory.sendChatToServer(message = result['msg_body'], outcome = result['outcome'])
            # If Wit did not succeeded
            elif len(result) == 0 or result.has_key('outcome') == False or result['outcome'].has_key('confidence') == False or result['outcome']['confidence'] < self.configuration['wit_confidence']:
                if wit_e is not None:
                    log.err("Wit exception : {0}".format(str(e)))
                elif len(result) == 0:
                    log.err("No response from Wit")
                elif result.has_key('outcome') == False or result['outcome'].has_key('confidence') == False:
                    log.err("Wit response syntax error")
                    log.err("result : {0}".format(result))
                elif result['outcome']['confidence'] < self.configuration['wit_confidence']:
                    log.err("Wit confidence {confidence} too low : {result}".format(confidence = result['outcome']['confidence'], result = result['msg_body']))
                else:
                    log.err("Error response from Wit : {0}".format(result['msg_body']))

            # Send recognized intent to the server
            else:
                log.msg("Wit result : {0}".format(result['msg_body']))
                self.factory.sendChatToServer(message = result['msg_body'], outcome = result['outcome'])

            # Finish current record
            self.record['start'] = 0
            self.record['started'] = False
            self.record['end'] = 0
            self.record['ended'] = False
            self.record['activated'] = False
            self.record['buffers'].clear()

    #-----------------------------------------------------------------------------
    def vaderStart(self):
        """
        Vader start detection
        """
        # If record is running
        if self.record['ended'] == False:
            # New start
            if self.record['started'] == False:
                self.record['started'] = True
                self.record['start'] = time()

            # Reset max recording time
            self.record['end'] = self.record['start'] + MAX_RECORD_DURATION_s

    #-----------------------------------------------------------------------------
    def vaderStop(self):
        """
        Vader stop detection
        """
        # If record is running
        if self.record['ended'] == False and self.record['end'] > time() + MAX_SILENCE_s:
            # End recording when no new activity during next silence
            self.record['end'] = time() + MAX_SILENCE_s

    #-----------------------------------------------------------------------------
    def _captureAudioBuffer(self, app):
        """
        Gstreamer pipeline callback : Audio buffer capture
        """
        # Get buffer
        buf = self.rec_sink.emit('pull-buffer')

        # If record is running
        if self.record['started'] == True and self.record['ended'] == False:
            cur_time = time()

            # Add buffer to queue
            self.record['buffers'].append({'time' : cur_time, 'data' : buf})

            # Delete too old buffers when utter is not activated
            if self.record['activated'] == False and self.continuous_mode == False:
                while self.record['buffers'][0]['time'] + MAX_TIME_BEFORE_KWS_s < cur_time:
                    self.record['buffers'].popleft()

    #-----------------------------------------------------------------------------
    def _readAudioBuffer(self, file_mode = False):
        """
        Read buffers from capture queue
        """
        # Check current record
        if self.record['activated'] == False and self.continuous_mode == False:
            return

        f = None
        if file_mode == True:
            f = open(self.temp_file, "wb")

        # While recording is running
        log.msg("Wit send start")
        while not self._stopevent.isSet():
            # Test if record is ended
            if self.record['ended'] == False and self.record['end'] <= time():
                self.record['ended'] = True

            # If there is no captured buffer
            if len(self.record['buffers']) == 0:
                # No more buffer when record is ended, it's over
                if self.record['ended'] == True:
                    break

                # Record is live, wait another buffer
                sleep(.05)
                continue

            # Read buffer
            buf = None
            while len(self.record['buffers']) > 0 and (buf is None or len(buf) + len(self.record['buffers'][0]['data']) < 1200):
                data = self.record['buffers'].popleft()
                if buf is None:
                    buf = data['data']
                else:
                    buf = buf.merge(data['data'])
            if file_mode == True:
                f.write(buf)
            yield buf

        if file_mode == True:
            f.close()
        log.msg("Wit send end")

# --------------------- End of recorder.py  ---------------------
