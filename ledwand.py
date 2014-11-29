#!/usr/bin/python3
# -*- coding: utf-8 -*-

import gi, signal, logging, sys, socket, time, ledcontrol

# import GStreamer and GTK-Helper classes
gi.require_version('Gst', '1.0')
from gi.repository import GLib, Gst, GObject

# init GObject before importing local classes
GObject.threads_init()
Gst.init(None)

# main class
class Ledwand:
	log = logging.getLogger('Ledwand')

	def __init__(self):
		self.mainloop = GObject.MainLoop()
		self.lc = ledcontrol.LedCtrl()

		# initialize subsystem
		self.pipeline = Gst.Pipeline()

		#self.testsrc = Gst.ElementFactory.make('videotestsrc', None)
		#self.testsrc.set_property("pattern", "ball")
		#self.pipeline.add(self.testsrc)

		self.avsrc = Gst.ElementFactory.make('uridecodebin', None)
		self.avsrc.set_property("uri", "file:///home/peter/Sintel.2010.720p.mkv")
		self.avsrc.connect('pad-added', self.pad_added)
		self.pipeline.add(self.avsrc)


		self.conv = Gst.ElementFactory.make('videoconvert', None)
		self.pipeline.add(self.conv)

		self.scale = Gst.ElementFactory.make('videoscale', None)
		self.pipeline.add(self.scale)

		self.appsink = Gst.ElementFactory.make('appsink', None)
		self.pipeline.add(self.appsink)

		self.avsrc.link(self.conv)
		self.conv.link_filtered(self.scale, Gst.Caps.from_string('video/x-raw,format=RGB'))
		self.scale.link_filtered(self.appsink, Gst.Caps.from_string('video/x-raw,width=32,height=32'))


		#self.appsink.set_property('sync', False)
		self.appsink.set_property('emit-signals', True)
		#self.appsink.set_property('drop', True)
		self.appsink.connect('new-sample', self.new_sample)

	def pad_added(self, element, pad):
		dstpad = self.conv.get_static_pad('sink')
		capsstr = pad.query_caps(None).to_string()

		self.log.debug('on_pad_added: %s', capsstr)
		if capsstr.startswith('video/x-raw') and not dstpad.is_linked(): # Only link once
			self.log.debug('linking')
			pad.link(dstpad)

	def new_sample(self, appsink):
		self.log.debug("Trying to pull sample")
		sample = appsink.emit('pull-sample')
		buf = sample.get_buffer() 
		data = buf.extract_dup(0, buf.get_size())
		self.lc.send_frame(2, data)

		#caps = sample.get_caps()
		#print(caps.to_string())
		#print(sample)
		return False

	def run(self):
		self.log.info('running Video-Pipeline')
		self.pipeline.set_state(Gst.State.PAUSED)
		time.sleep(0.5)
		self.pipeline.set_state(Gst.State.PLAYING)

		self.log.info('running GObject-MainLoop')
		self.mainloop.run()

	def kill(self):
		self.log.info('quitting Video-Pipeline')
		self.pipeline.quit()

		self.log.info('quitting GObject-MainLoop')
		self.mainloop.quit()

	def on_eos(self, bus, msg):
		self.log.warning('received EOS-Signal on the Video-Bus from Element %s. This shouldn\'t happen if the program is not terminating right now', msg.src)
		self.kill()

	def on_error(self, bus, msg):
		err = msg.parse_error()
		self.log.error('received Error-Signal on the Video-Bus from Element %s: %s', msg.src, err[1])
		self.kill()


# run mainclass
def main(argv):
	# configure logging
	logging.basicConfig(level=logging.DEBUG,
		format='%(levelname)8s %(name)s: %(message)s')

	# make killable by ctrl-c
	logging.debug('setting SIGINT handler')
	signal.signal(signal.SIGINT, signal.SIG_DFL)

	# init main-class and main-loop
	logging.debug('initializing Voctocore')
	ledwand = Ledwand()

	logging.debug('running ledwand')
	ledwand.run()

if __name__ == '__main__':
	main(sys.argv)
