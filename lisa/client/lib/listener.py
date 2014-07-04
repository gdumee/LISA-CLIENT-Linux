# -*- coding: UTF-8 -*-

# Imports
import pygst
pygst.require('0.10')
import gobject
gobject.threads_init()
from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop(set_as_default=True)
import gst, os, string
from time import sleep,time
import threading
try: # It fixes a bug with the pocketpshinx import. The first time it fails, but the second import is ok.
    import pocketsphinx
except:
    pass
import pocketsphinx
from twisted.python import log
from lisa.client.lib.speaker import Speaker
from lisa.client.lib.recorder import Recorder
from lisa.client.ConfigManager import ConfigManagerSingleton

# Current path
PWD = os.path.dirname(os.path.abspath(__file__))

# Global configuration
NUM_PIPES = 2
VADER_MAX_LENGTH = 1


class Listener(threading.Thread):
    """
    The goal is to listen for a keyword, then it starts a voice recording
    """

    def __init__(self, lisa_client, botname):
        # Init thread class
        threading.Thread.__init__(self)
        self._stopevent = threading.Event()

        configuration = ConfigManagerSingleton.get().getConfiguration()
        self.botname = lisa_client.botname.lower()
        self.scores = []
        self.pipes = [{'vad' : None, 'ps' : None, 'start' : 0}] * NUM_PIPES
        self.keyword_score = -10000
        if configuration.has_key("keyword_score"):
            self.keyword_score = configuration['keyword_score']

        # Find client path
        if os.path.isdir('/var/lib/lisa/client/pocketsphinx'):
            client_path = '/var/lib/lisa/client/pocketsphinx'
        else:
            client_path = "%s/pocketsphinx" % PWD

        # Build Gstreamer pipeline : mic->Pulse->tee|->queue->audioConvert->audioResample->vader->pocketsphinx->fakesink
        #                                           |->queue->audioConvert->audioResample->lamemp3enc->appsink
        # fakesink : async=false is mandatory for parallelism
        pipeline = 'pulsesrc ! audioconvert' \
                    + ' ! tee name=audio_tee' \
                    + ' audio_tee.' \
                    + ' ! queue' \
                    + ' ! audioconvert ! audioresample' \
                    + ' ! audio/x-raw-int, format=(string)S16_LE, channels=1, rate=16000' \
                    + ' ! lamemp3enc bitrate=64 mono=true' \
                    + ' ! appsink name=rec_sink emit-signals=true async=false' \
                    + ' audio_tee.' \
                    + ' ! queue ! audiocheblimit mode=1 cutoff=150' \
                    + ' ! audiodynamic ! audioconvert ! audioresample' \
                    + ' ! tee name=asr_tee'
        
        # Add pocketsphinx
        for i in range(NUM_PIPES):
            pipeline = pipeline \
                    + ' asr_tee.' \
                    + ' ! vader name=vad_%d auto-threshold=true' % (i) \
                    + ' ! pocketsphinx name=asr_%d' % (i) \
                    + ' ! fakesink async=false'

        # Create pipeline
        self.pipeline = gst.parse_launch(pipeline)

        # Configure pipes
        for i in range(NUM_PIPES):
            # Initialize vader
            vader = self.pipeline.get_by_name('vad_%d' % i)
            vader.connect('vader-start', self._vader_start, i)
            vader.connect('vader-stop', self._vader_stop, i)
            self.pipes[i]['vad'] = vader

            # Initialize pocketsphinx
            asr = self.pipeline.get_by_name('asr_%d' % i)
            asr.set_property("dict", "%s/%s.dic" % (client_path, self.botname))
            asr.set_property("lm", "%s/%s.lm" % (client_path, self.botname))
            if configuration.has_key("hmm"):
                if os.path.isdir(configuration["hmm"]):
                    asr.set_property("hmm", configuration["hmm"])
                else:
                    hmm_path = "%s/%s" % (client_path, configuration["hmm"])
                    if os.path.isdir(hmm_path):
                        asr.set_property("hmm", hmm_path)
            asr.connect('result', self._asr_result, i)
            asr.set_property('configured', 1)
            
            # TODO 
            self.pipes[i]['ps'] = pocketsphinx.Decoder(boxed = asr.get_property('decoder'))

        # Create recorder
        self.recorder = Recorder(lisa_client = lisa_client, listener = self)

        # Start thread
        self.start()

    def run(self):
        """
        Listener main loop
        """
        Speaker.speak("ready")
        self.pipeline.set_state(gst.STATE_PLAYING)

        # Thread loop
        while not self._stopevent.isSet():
            for vader in self.pipes:
                if vader['start'] > 0 and time() >= vader['start'] + VADER_MAX_LENGTH:
                    # Force silent to cut current utterance
                    vader['vad'].set_property('silent', True)
                    vader['vad'].set_property('silent', False)
            sleep(.05)

        # Stop pipeline
        self.pipeline.set_state(gst.STATE_NULL)
        self.pipeline = None

    def stop(self):
        """
        Stop listener.
        """
        Speaker.speak('lost_server')

        # Stop everything
        self._stopevent.set()
        self.pipeline.set_state(gst.STATE_NULL)
        self.recorder.stop()

    def _vader_start(self, ob, message, pipe_id):
        """
        Vader start detection
        """
        self.pipes[pipe_id]['start'] = time()
        self.recorder.vader_start()

    def _vader_stop(self, ob, message, pipe_id):
        """
        Vader stop detection
        """
        self.pipes[pipe_id]['start'] = 0
        self.recorder.vader_stop()

    def _asr_result(self, asr, text, uttid, pipe_id):
        """
        Result from pocketsphinx : checking keyword recognition
        """
        # Get score from decoder
        # TODO
        #dec_score = string.atoi(uttid)
        dec_text, dec_uttid, dec_score = self.pipes[pipe_id]['ps'].get_hyp()

        # Detection must have a minimal score to be valid
        if dec_score != 0 and dec_score < self.keyword_score:
            log.msg("I recognized the %s keyword but I think it's a false positive according the %s score" % (self.botname, dec_score))
            return

        # Activate recorder
        self.recorder.activate()

        # Logs
        self.scores.append(dec_score)
        log.msg("======================")
        log.msg("%s keyword detected" % self.botname)
        log.msg("score: {} (min {}, moy {}, max {})".format(dec_score, min(self.scores), sum(self.scores) / len(self.scores), max(self.scores)))

    def get_pipeline(self):
        """
        Return Gstreamer pipeline
        """
        return self.pipeline
