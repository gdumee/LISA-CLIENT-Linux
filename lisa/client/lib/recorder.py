# -*- coding: UTF-8 -*-

# Imports
from lisa.client.ConfigManager import ConfigManagerSingleton
from collections import deque
import threading
from wit import Wit
import time
from time import sleep,time
from twisted.python import log

# Max silence before considering the end of the utterance
MAX_SILENCE_s = 1

# Maximum record duration in seconds
MAX_RECORD_DURATION_s = 10

# Maximum record length before keyword spot
MAX_TIME_BEFORE_KWS_s = 5


class Recorder(threading.Thread):
    def __init__(self, lisa_client, listener):
        # Init thread class
        threading.Thread.__init__(self)
        self._stopevent = threading.Event()

        self.lisa_client = lisa_client
        self.configuration = ConfigManagerSingleton.get().getConfiguration()
        self.pipeline = listener.get_pipeline()
        self.running_state = False
        self.wit = Wit(self.configuration['wit_token'])
        self.wit_confidence = 0.5
        if self.configuration.has_key('confidence'):
            self.wit_confidence = self.configuration['wit_confidence']
        self.records = []

        # Get app sink
        self.rec_sink = self.pipeline.get_by_name('rec_sink')
        self.rec_sink.connect('new-buffer', self._capture_audio_buffer)

        # Start thread
        self.start()

    def stop(self):
        # Raise stop event
        self._stopevent.set()

    def activate(self):
        """
        Called to activate current utter as a record
        """
        # If there is a current record
        # TODO if several records, which one to activate?
        if len(self.records) > 0 and self.records[-1]['finished'] == False:
            # Activate record
            self.records[-1]['activated'] = True

    def run(self):
        """
        Recorder main loop
        """
        CONTENT_TYPE = 'audio/mpeg3'

        # Thread loop
        while not self._stopevent.isSet():
            # If there is a current record
            if len(self.records) == 0:
                sleep(.1)
                continue

            # Finish if end reached
            if self.records[-1]['finished'] == False and self.records[-1]['end'] <= time():
                self.records[-1]['finished'] = True
            
            # Delete finished records that were not activated
            while len(self.records) > 0 and self.records[0]['finished'] == True and self.records[0]['activated'] == False:
                self.records.pop(0)

            # Send activated records to Wit
            retry_flag = False
            while len(self.records) > 0 and self.records[0]['activated'] == True:
                wit_e = None
                result = ""
                try:
                    result = self.wit.post_speech(data = self._read_audio_buffer(), content_type = CONTENT_TYPE)
                except Exception as e:
                    wit_e = e

                # If record was stopped during recording
                if self._stopevent.isSet():
                    break

                # If Wit did not succeeded
                if len(result) == 0 or result.has_key('outcome') == False or result['outcome'].has_key('confidence') == False or result['outcome']['confidence'] < self.wit_confidence:
                    if wit_e is not None:
                        log.err("Wit exception : " + str(e))
                    elif len(result) == 0:
                        log.err("No response from Wit")
                    elif result.has_key('outcome') == False or result['outcome'].has_key('confidence') == False:
                        log.err("Wit response syntax error")
                        log.err("result : %s" % (str(result)))
                    elif result['outcome']['confidence'] < self.wit_confidence:
                        log.err("Wit confidence too low : " + result['msg_body'])

                # Send recognized intent to the server
                else:
                    log.msg("Wit result : " + result['msg_body'])
                    self.lisa_client.sendMessage(message = result['msg_body'], type = 'chat', dict = result['outcome'])

                # Remove sent record
                self.records.pop(0)

        # Finish current buffer
        for r in self.records:
            r['finished'] = True

    def vader_start(self):
        """
        Vader start detection
        """
        # Create a new record if needed
        if len(self.records) == 0 or self.records[-1]['finished'] == True:
            self.records.append({'finished' : False, 'activated' : False, 'start' : time(), 'end' : 0, 'buffers' : deque({})})

        # Reset max recording time
        self.records[-1]['end'] = self.records[-1]['start'] + MAX_RECORD_DURATION_s
        
    def vader_stop(self):
        """
        Vader stop detection
        """
        # End recording when no new activity during next silence
        if len(self.records) > 0 and self.records[-1]['end'] > time() + MAX_SILENCE_s:
            self.records[-1]['end'] = time() + MAX_SILENCE_s

    def _capture_audio_buffer(self, app):
        """
        Gstreamer pipeline callback : Audio buffer capture
        """
        # Get buffer
        buf = self.rec_sink.emit('pull-buffer')

        # If a record is running
        if len(self.records) > 0 and self.records[-1]['finished'] == False:
            cur_time = time()

            # Add buffer to queue
            self.records[-1]['buffers'].append({'time' : cur_time, 'data' : buf})

            # Delete too old buffers when utter is not activated
            if self.records[-1]['activated'] == False:
                while self.records[-1]['buffers'][0]['time'] + MAX_TIME_BEFORE_KWS_s < cur_time:
                    self.records[-1]['buffers'].popleft()
            
    def _read_audio_buffer(self):
        """
        Read buffers from capture queue
        """
        last_progress = -1

        # Check current record
        if len(self.records) == 0 or self.records[0]['activated'] == False:
            return
        
        filename = "/home/ubuntu/record.mp3"
        f = open(filename, "w")
        
        # While recording is running
        log.msg("Wit send start")
        while not self._stopevent.isSet() and len(self.records) > 0:
            # If there is no captured buffer
            if len(self.records[0]['buffers']) == 0:
                # When record is finished, it's over
                if self.records[-1]['end'] <= time():
                    self.records[-1]['finished'] = True
                    log.msg("Wit send end")
                    break
                else:
                    # Wait another buffer
                    sleep(.05)
                    continue
            
            # Read buffer
            buf = None
            while len(self.records[0]['buffers']) > 0 and (buf is None or len(buf) + len(self.records[0]['buffers'][0]['data']) < 1200):
                data = self.records[0]['buffers'].popleft()
                if buf is None:
                    buf = data['data']
                else:
                    buf = buf.merge(data['data'])
            yield buf
            f.write(buf)

        f.close()
