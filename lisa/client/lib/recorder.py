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
from lisa.client.ConfigManager import ConfigManagerSingleton
from lisa.client.lib.player import Player
from collections import deque
import threading
from wit import Wit
import time
from time import sleep,time
from twisted.python import log
import urllib2
from urllib2 import Request, urlopen
from subprocess import call


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
    def __init__(self, lisa_client):
        # Init thread class
        threading.Thread.__init__(self)
        self._stopevent = threading.Event()

        self.lisa_client = lisa_client
        self.configuration = ConfigManagerSingleton.get().getConfiguration()
        self.wit = Wit(self.configuration['wit_token'])
        self.wit_confidence = 0.5
        if self.configuration.has_key('confidence'):
            self.wit_confidence = self.configuration['wit_confidence']
        self.record = {'activated' : False, 'start' : 0, 'started' : False, 'end' : 0, 'ended' : False, 'buffers' : deque({}), 'question_mode': False}

    #-----------------------------------------------------------------------------
    def start(self, listener):
        # Get app sink
        self.listener = listener
        self.rec_sink = listener.get_pipeline().get_by_name('rec_sink')
        self.rec_sink.connect('new-buffer', self._capture_audio_buffer)
        
        # Start thread
        threading.Thread.start(self)

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
    def activate_question(self):
        """
        Called to activate current utter as a record
        """
        # Activate record
        self.record['question_mode'] = True
        self.record['activated'] = True

    #-----------------------------------------------------------------------------
    def run(self):
        """
        Recorder main loop
        """
        CONTENT_TYPE = 'audio/mpeg3'

        # Thread loop
        while not self._stopevent.isSet():
            # Test if record is ended
            if self.record['started'] == True and self.record['ended'] == False and self.record['end'] <= time():
                # If current record was not activated before end
                if self.record['activated'] == False:
                    self.record['start'] = 0
                    self.record['started'] = False
                    self.record['end'] = 0
                    self.record['ended'] = False
                    self.record['activated'] = False
                    
                    continue
                
                # Current record is activated and already ended
                self.record['ended'] = True

            # If current record is not activated
            if self.record['activated'] == False:
                sleep(.1)
                continue

            # Send activated record to Wit
            wit_e = None
            result = ""
            try:
                result = self.wit.post_speech(data = self._read_audio_buffer(), content_type = CONTENT_TYPE)
                result['msg_body'] = result['msg_body'].encode("utf-8")
            except Exception as e:
                wit_e = e

            # If record was stopped during Wit access
            if self._stopevent.isSet():
                break

            # Question mode
            if len(result) > 0 and self.record['question_mode'] == True and result.has_key('msg_body') == True and len(result['msg_body']) > 0:
                # Send answer
                self.lisa_client.sendAnswer(message = result['msg_body'], dict = result['outcome'])
            # If Wit did not succeeded
            elif len(result) == 0 or result.has_key('outcome') == False or result['outcome'].has_key('confidence') == False or result['outcome']['confidence'] < self.wit_confidence:
                if wit_e is not None:
                    log.err("Wit exception : {0}".format(str(e)))
                elif len(result) == 0:
                    log.err("No response from Wit")
                elif result.has_key('outcome') == False or result['outcome'].has_key('confidence') == False:
                    log.err("Wit response syntax error")
                    log.err("result : {0}".format(result))
                elif result['outcome']['confidence'] < self.wit_confidence:
                    log.err("Wit confidence {confidence} too low : {result}".format(confidence = result['outcome']['confidence'], result = result['msg_body']))
                else:
                    log.err("Error response from Wit : {0}".format(result['msg_body']))

            # Send recognized intent to the server
            else:
                log.msg("Wit result : {0}".format(result['msg_body']))
                self.lisa_client.sendMessage(message = result['msg_body'], type = 'chat', dict = result['outcome'])

            # Finish current record
            self.record['start'] = 0
            self.record['started'] = False
            self.record['end'] = 0
            self.record['ended'] = False
            self.record['activated'] = False
            self.record['buffers'].clear()
            self.record['question_mode'] = False

    #-----------------------------------------------------------------------------
    def vader_start(self):
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
    def vader_stop(self):
        """
        Vader stop detection
        """
        # If record is running
        if self.record['ended'] == False and self.record['end'] > time() + MAX_SILENCE_s:
            # End recording when no new activity during next silence
            self.record['end'] = time() + MAX_SILENCE_s

    #-----------------------------------------------------------------------------
    def _capture_audio_buffer(self, app):
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
            if self.record['activated'] == False:
                while self.record['buffers'][0]['time'] + MAX_TIME_BEFORE_KWS_s < cur_time:
                    self.record['buffers'].popleft()
            
    #-----------------------------------------------------------------------------
    def _read_audio_buffer(self):
        """
        Read buffers from capture queue
        """
        # Check current record
        if self.record['activated'] == False:
            return
        
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
            yield buf

        log.msg("Wit send end")
        
# --------------------- End of recorder.py  ---------------------
