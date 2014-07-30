# -*- coding: UTF-8 -*-
#-----------------------------------------------------------------------------
# project     : Lisa client
# module      : client
# file        : service.py
# description : Lisa client twisted service
# author      : G.Dumee
#-----------------------------------------------------------------------------
# copyright   : Neotique
#-----------------------------------------------------------------------------


#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------
from twisted.python import log
import signal
gobjectnotimported = False
try:
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    import gobject
    import pygst
    pygst.require('0.10')
    gobject.threads_init()
    from lisa.client import lib
    from lib import Listener
    from lib import Player
    from lib import Speaker
except:
    gobjectnotimported = True
from twisted.internet import ssl, utils
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.internet.defer import inlineCallbacks, DeferredQueue
from twisted.application.internet import TCPClient
from twisted.protocols.basic import LineReceiver
from twisted.application import internet, service
from twisted.internet import reactor
from lisa.client.config_manager import ConfigManager
import json, os
from OpenSSL import SSL


#-----------------------------------------------------------------------------
# Globals
#-----------------------------------------------------------------------------
# Creating MultiService
application = service.Application("LISA-Client")

# Client protocol factory
LisaFactory = None


#-----------------------------------------------------------------------------
# LisaClient
#-----------------------------------------------------------------------------
class LisaClient(LineReceiver):
    """
    Lisa TCP client
    """

    #-----------------------------------------------------------------------------
    def __init__(self, factory):
        self.factory = factory
        self.configuration = ConfigManager.getConfiguration()

        self.debug_input = False
        self.debug_output = False
        if self.configuration.has_key("debug"):
            if self.configuration["debug"].has_key("debug_input"):
                self.debug_input = self.configuration["debug"]["debug_input"]
            if self.configuration["debug"].has_key("debug_output"):
                self.debug_output = self.configuration["debug"]["debug_output"]

        self.name = self.configuration['client_name']
        self.zone = self.configuration['zone']

    #-----------------------------------------------------------------------------
    def sendToServer(self, jsonData):
        # Add info to json
        jsonData['from'] = self.name
        jsonData['zone'] = self.zone
        jsonData['to'] = 'Server'

        if self.debug_output:
            log.msg('OUTPUT: {0}'.format(jsonData))

        # Send line to the server
        self.sendLine(json.dumps(jsonData))

    #-----------------------------------------------------------------------------
    def sendChatToServer(self, message, outcome = None):
        json = {'type': 'chat', 'message': message}
        if outcome is not None:
            json['outcome'] = outcome
        self.sendToServer(json)

    #-----------------------------------------------------------------------------
    def lineReceived(self, data):
        """
        Data received callback
        The nolistener in configuration is here to let the travis build pass without loading gst
        """
        datajson = json.loads(data)
        if self.debug_input == True:
            log.msg("INPUT: {0}".format(str(datajson)))

        if datajson.has_key("type"):
            datajson['type'] = datajson['type'].lower()
            if datajson['type'] == 'chat':
                if datajson.has_key('nolistener') == False:
                    Speaker.speak(datajson['message'])

            if datajson['type'].lower() == 'error':
                log.err(datajson['message'])
                if datajson.has_key('nolistener') == False:
                    Speaker.speak(datajson['message'])

            elif datajson['type'] == 'command':
                datajson['command'] = datajson['command'].lower()
                if datajson['command'] == 'login ack':
                    # Get Bot name
                    botname = datajson['bot_name'].lower()
                    log.msg("setting botname to {0}".format(botname))
                    self.factory.setBotName(botname)

                elif datajson['command'] == 'ask':
                    if datajson.has_key('nolistener') == False and datajson.has_key('message'):
                        Speaker.speak(datajson['message'])

                    # Set continuous mode
                    if datajson.has_key('nolistener') == False:
                        wit_context = None
                        if datajson.has_key('wit_context') == True:
                            wit_context = datajson['wit_context']
                        self.factory.setContinuousMode(enabled = True, wit_context = wit_context)

                elif datajson['command'] == 'kws':
                    if datajson.has_key('nolistener') == False and datajson.has_key('message'):
                        Speaker.speak(datajson['message'])

                    # Set KWS mode
                    if datajson.has_key('nolistener') == False:
                        wit_context = None
                        if datajson.has_key('wit_context') == True:
                            wit_context = datajson['wit_context']
                        self.factory.setContinuousMode(enabled = False, wit_context = wit_context)

        else:
            # Send to TTS queue
            if datajson.has_key('nolistener') == False and datajson.has_key('message'):
                Speaker.speak(datajson['message'])

    #-----------------------------------------------------------------------------
    def connectionMade(self):
        """
        Callback on established connections
        """
        log.msg('Connected to the server.')

        # Set SSL encryption
        if self.configuration['enable_secure_mode'] == True:
            ctx = ClientTLSContext()
            self.transport.startTLS(ctx, self.factory)

        # Login to server
        json = {'type': 'command', 'command': "login req"}
        self.sendToServer(json)


#-----------------------------------------------------------------------------
# LisaClientFactory
#-----------------------------------------------------------------------------
class LisaClientFactory(ReconnectingClientFactory):
    # Create protocol
    active_protocol = None

    #-----------------------------------------------------------------------------
    def __init__(self):
        self.configuration = ConfigManager.getConfiguration()
        self._ = self.configuration['trans']
        self.active_protocol = None
        self.warn_on_connect = False
        self.running_state = True
        self.listener = None

    #-----------------------------------------------------------------------------
    def setBotName(self, botname):
        # Restart listener with new botname
        self.listener.setBotName(botname)

    #-----------------------------------------------------------------------------
    def sendChatToServer(self, message, outcome = None):
        # If not connected to the server
        if self.active_protocol is None:
            Speaker.speak(self._('no_server'))
            self.warn_on_connect = True
            return

        # Send chat to server
        self.active_protocol.sendChatToServer(message = message, outcome = outcome)

    #-----------------------------------------------------------------------------
    def setContinuousMode(self, enabled, wit_context = None):
        # Change continuous mode in recorder
        self.listener.setContinuousMode(enabled = enabled, wit_context = wit_context)

    #-----------------------------------------------------------------------------
    def buildProtocol(self, addr):
        # Create workers
        if self.listener is None:
            self.listener = Listener(factory = self)
            Speaker.start(listener = self.listener)

        # Reset retry delay
        self.resetDelay()

        # Warn on connection
        if self.warn_on_connect == True:
            Speaker.speak(self._('back_ready'))
            self.warn_on_connect = False

        # Return protocol
        self.active_protocol = LisaClient(factory = self)
        return self.active_protocol

    #-----------------------------------------------------------------------------
    def clientConnectionLost(self, connector, reason):
        # Delete current connection
        self.active_protocol = None

        # Retry connection to the server
        log.err('Lost connection.  Reason: {0}'.format(reason.getErrorMessage()))
        if self.running_state == True:
            ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    #-----------------------------------------------------------------------------
    def clientConnectionFailed(self, connector, reason):
        # Retry
        self.resetDelay()
        log.err('Connection failed. Reason: {0}'.format(reason.getErrorMessage()))
        if self.running_state == True:
            ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)

    #-----------------------------------------------------------------------------
    def stop(self):
        # Stop workers
        self.running_state = False
        self.listener.stop()
        self.listener = None
        Speaker.stop()


#-----------------------------------------------------------------------------
# ClientTLSContext
#-----------------------------------------------------------------------------
class ClientTLSContext(ssl.ClientContextFactory):
    isClient = 1
    def getContext(self):
        return SSL.Context(SSL.TLSv1_METHOD)


#-----------------------------------------------------------------------------
# ClientAuthContextFactory
#-----------------------------------------------------------------------------
class ClientAuthContextFactory(ssl.ClientContextFactory):
    def getContext(self):
        self.method = SSL.SSLv23_METHOD
        ctx = ssl.ClientContextFactory.getContext(self)
        configuration = ConfigManager.getConfiguration()
        ctx.use_certificate_file(configuration['lisa_engine_ssl_crt'])
        ctx.use_privatekey_file(configuration['lisa_engine_ssl_key'])
        return ctx


#-----------------------------------------------------------------------------
# Handle Ctrl-C
#-----------------------------------------------------------------------------
def sigint_handler(signum, frame):
    global LisaFactory

    # Unregister handler, next Ctrl-C will kill app
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Stop factory
    if LisaFactory is not None:
        LisaFactory.stop()
        LisaFactory = None

    # Stop reactor
    reactor.stop()


#-----------------------------------------------------------------------------
# Make twisted service
#-----------------------------------------------------------------------------
def makeService(config):
    global LisaFactory

    # Get configuration
    if config['configuration']:
        if ConfigManager.setConfiguration(config_file = config['configuration']) == False:
            Speaker.start()
            Speaker.speak(ConfigManager.getConfiguration()['trans']("error_conf"))
            return

    # Multiservice mode
    multi = service.MultiService()
    multi.setServiceParent(application)

    # Ctrl-C handler
    signal.signal(signal.SIGINT, sigint_handler)

    # Create factory
    LisaFactory = LisaClientFactory()

    # Start client factory
    configuration = ConfigManager.getConfiguration()
    if configuration['enable_secure_mode'] == True:
        lisaclientService = internet.SSLClient(configuration['lisa_url'], configuration['lisa_port'], LisaFactory, ClientAuthContextFactory())
    else:
        lisaclientService = internet.TCPClient(configuration['lisa_url'], configuration['lisa_port'], LisaFactory)
    lisaclientService.setServiceParent(multi)

    return multi

# --------------------- End of service.py  ---------------------
