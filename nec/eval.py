# Copyright 2010-2012 Nikolay Mladenov, Distributed under 
# GNU General Public License

import sys, traceback, os, pprint
from nec import necmath
from nec.demathutils import v3add, v3mul, v3sub, v3dot, v3cross, v3len, v3unit, v3rotx, v3roty, v3rotz

output = "output"
input = "input.nec"
autosegmentation=10
ncores=4

def printOut(s):
	if type(s)!=type(''):
		s = str(s)
	sys.stdout.write(s)
	sys.stdout.write('\n')
	sys.stdout.flush()

class GeometryError (RuntimeError):
	def __init__(self, msg):
		RuntimeError.__init__(self,msg)

class Sweep:
	def __init__(self, ranges, angles, agt_freq,sweepid):
		self.ranges = ranges
		self.angles = angles
		self.agt_freq = agt_freq
		self.sweepid = sweepid
	def __str__(self):
		return "{"+str(self.ranges)+", agt freq "+str(self.agt_freq)+"}"
	def __repr__(self):
		return "{"+str(self.ranges)+", agt freq "+str(self.agt_freq)+"}"


class FrequencyData:
	def __init__(self, char_impedance):
		self.freq = 0
		self.real = 0
		self.imag = 0
		self.gain = 0
		self.char_impedance = char_impedance
		self.angle = 0
		self.AGT = 1.0
		self.agt = 0
		self.horizontal = {}
		self.vertical = {}
		self.sorted_horizontal_angles = []
		self.input_power = 0
		self.radiated_power = 0
		self.structure_loss = 0
		self.network_loss = 0
		self.efficiency = 0

	def swr(self):
		rc = necmath.sqrt( \
			(necmath.pow(self.real-self.char_impedance,2)+necmath.pow(self.imag,2)) \
			/ (necmath.pow(self.real+self.char_impedance,2)+necmath.pow(self.imag,2)) \
			)
		return (1+rc)/(1-rc)
	def valid(self):
		try: 
			self.swr()
			return 1
		except:
			return 0
	def net(self, g = None):
		if g is None:
			g = self.gain
		tmp = 4*max(self.real,.0001)*self.char_impedance/(necmath.pow(self.real+self.char_impedance,2)+necmath.pow(self.imag,2))
		return g+10*necmath.log10(tmp)

	def horizontalNet(self, phi):
		return self.net(self.horizontalRaw(phi))

	def horizontalRaw(self, phi):
		if phi in self.horizontal: return self.horizontal[phi]
		#sys.stderr.write("WARNING: gain for angle %.1f not calculated - using approximation\n"%phi)
		#sys.stderr.write(str(self.horizontal)+"\n")
		if not self.sorted_horizontal_angles:
			self.sorted_horizontal_angles = sorted(self.horizontal.keys())
		if not self.sorted_horizontal_angles:
			raise RuntimeError("gain not calculated")
		diff = phi-self.sorted_horizontal_angles[0]
		index = 0
		for i in range(1,len(self.sorted_horizontal_angles)):
			d = phi-self.sorted_horizontal_angles[i]
			if abs(d) < abs(diff):
				diff = d
				index = i
		if index !=0 and diff < 0:
			return (self.horizontal[self.sorted_horizontal_angles[index-1]]*(phi - self.sorted_horizontal_angles[index-1])		\
					+ self.horizontal[self.sorted_horizontal_angles[index]]*( self.sorted_horizontal_angles[index] - phi) )	\
					/ (self.sorted_horizontal_angles[index]-self.sorted_horizontal_angles[index-1])
		if index !=len(self.sorted_horizontal_angles)-1 and diff > 0:
			return (self.horizontal[self.sorted_horizontal_angles[index+1]]*(self.sorted_horizontal_angles[index+1]-phi)		\
					+ self.horizontal[self.sorted_horizontal_angles[index]]*(phi - self.sorted_horizontal_angles[index]) )	\
					/ (self.sorted_horizontal_angles[index+1]-self.sorted_horizontal_angles[index])
		return self.horizontal[self.sorted_horizontal_angles[index]]

	def verticalNet(self, theta):
		return self.net(self.vertical[theta])
		
	def __str__(self):
		return "%d Mhz - raw(%f), net(%f), swr(%f), real(%f), imag(%f)"%(int(self.freq), self.gain, self.net(), self.swr(), self.real, self.imag)

	def forwardGain(self, forward_dir = 0):
		return self.horizontalNet(forward_dir)

	def forwardRaw(self, forward_dir = 0):
		return self.horizontalRaw(forward_dir)

	def backwardGain(self, backward_dir = 0):
		return self.horizontalNet(backward_dir)

	def backwardRaw(self, backward_dir = 0):
		return self.horizontalRaw(backward_dir)

	def rearGain(self, rear_angle, backward_dir = 180):
		rear = [self.horizontalNet(phi) for phi in self.horizontal.keys() if phi>=backward_dir-rear_angle/2. and  phi<=backward_dir+rear_angle/2.]
		if not rear:
			return None
		return max(rear)

		


class NecOutputParser:
	def __init__(self, output, agt, options):
		self.frequencies = []
		self.AGT = agt
		self.agt = 10*necmath.log10(agt)
		self.options = options
		if output:
			self.parse(output)

	def printFreqs(self, header=1):
		if not self.options.frequency_data:
			if header: 
				printOut( "%6s %8s %8s %7s %7s %7s %8s %8s %12s"%("Freq", "RawGain", "NetGain", "SWR", "F/R", "F/B", "Real", "Imag", "AGT(corr)"))
				printOut( "==================================================================================")
			#if self.agt!=0:
			#	printOut( "AGT=%g dB"%self.agt)
			for i in self.frequencies:
				if not i.valid():
					printOut( "%6.1f - invalid result"%i.freq)
				else:
					rear = "n/a"
					back = "n/a"
					raw = "n/a"
					net = "n/a"
					if self.options.calc.gain:
						raw = i.horizontalRaw(self.options.forward_dir)
						net = i.net(raw)
						if self.options.calc.f2r:
							rear = i.rearGain(self.options.rear_angle,self.options.backward_dir)
							rear = "% 7.3f"%(net-rear)
						if self.options.calc.f2b:
							back = i.backwardGain(self.options.backward_dir)
							back = "% 7.3f"%(net-back)
						raw = "% 8.3f"%raw
						net = "% 8.3f"%net

					printOut( "% 6.1f % 8s % 8s % 7.3f % 7s % 7s % 8.2f % 8.2f %5.2f(% 6.3f)"%	\
							(i.freq, raw, net,i.swr(), rear, back, i.real, i.imag, i.AGT, i.agt))

		else:
			if header: 
				printOut( "%6s %7s %6s %8s %8s %7s %8s %8s %7s %12s"%("Freq", "Target", "Angle", "RawGain", "NetGain", "SWR", "Real", "Imag", "Diff", "AGT(corr)"))
				printOut( "=========================================================================================")
			for i in self.frequencies:
				if not i.valid():
					printOut( "%6.4g - invalid result"%i.freq)
				else:
					target = self.options.frequency_data[i.freq][1]
					printOut( "% 6.1f % 7.2f % 6.1f % 8.3f % 8.3f % 7.3f % 8.2f % 8.2f % 7.3f %5.2f(% 6.3f)"%(i.freq, target, i.angle, i.gain, i.net(),i.swr(), i.real, i.imag, target-i.net(), i.AGT, i.agt))
	def getGainSWRChartData(self):
		res = []
		for i in self.frequencies:
			res.append((int(i.freq), i.net(),i.swr()))
		return res
	def horizontalPattern(self):
		res = {}
		for f in self.frequencies:
			res[f.freq] = [f.horizontalNet(phi) for phi in sorted(f.horizontal.keys())]
		
		return res

	def verticalPattern(self):
		res = {}
		for f in self.frequencies:
			res[f.freq] = [f.verticalNet(theta) for theta in sorted(f.vertical.keys())]
		
		return res

	def parse(self, output):
		file = open(output, "rt")
		try : 
			lines = file.readlines()
		finally:
			file.close()
		i=0
		freq = 0
		real = 0
		imag = 0
		while i < len(lines):
			ln = lines[i].strip()
			if ln == "- - - - - - FREQUENCY - - - - - -":
				i = i+2
				freq = float(lines[i].strip()[10:-4])
#				if not len(self.frequencies) or self.frequencies[-1].valid():
#					self.frequencies.append(FrequencyData(self.char_impedance))
#				self.frequencies[-1].freq = freq
			elif ln == "- - - ANTENNA INPUT PARAMETERS - - -":
				i=i+4
				real = float(lines[i][60:72]) # at least one linux engine has calculated negative real impedance...
				if real < 0:
					raise ValueError("engine reported negative real impedance for frequency %.1f"%freq)
				imag = float(lines[i][72:84])
#				self.frequencies[-1].real = float(lines[i][60:72])
#				self.frequencies[-1].imag = float(lines[i][72:84])
				fd = FrequencyData(self.options.char_impedance)
				fd.real = real
				fd.imag = imag
				self.frequencies.append(fd)
				fd.freq = freq
				fd.AGT = self.AGT
				fd.agt = self.agt

			elif ln == "- - - POWER BUDGET - - -":
				while i < len(lines):
					i+=1
					if len(lines[i]) < 60: continue
					if lines[0][43: 57] == "INPUT POWER   ": fd.input_power = float(lines[i][58:69])
					elif lines[0][43: 57] == "RADIATED POWER": fd.radiated_power = float(lines[i][58:69])
					elif lines[0][43: 57] == "STRUCTURE LOSS": fd.structure_loss = float(lines[i][58:69])
					elif lines[0][43: 57] == "NETWORK LOSS  ": fd.network_loss = float(lines[i][58:69])
					elif lines[0][43: 57] == "EFFICIENCY    ": 
						fd.efficiency = float(lines[i][58:65])
						break
					else: 
						break

				if fd.radiated_power < 0:
					raise ValueError("engine reported negative radiated power for frequency %.1f"%freq)
			elif ln =="- - - RADIATION PATTERNS - - -":
				i=i+5
				angle = self.options.forward_dir
#				freq = self.frequencies[-1].freq
				if freq in self.options.frequency_data.keys():
					angle = self.options.frequency_data[freq][0]
					while angle <0:angle+=360
					while angle >360:angle-=360
				while len(lines[i].strip()):
					ln = lines[i]
					if ln[0]=="*" or len(ln) < 8 :break
					try:
						#theta = float(ln[0:8])
						#phi = float(ln[8:17])
						#gain = float(ln[28:36])-self.agt
						ln = ln.split()
						theta = float(ln[0])
						phi = float(ln[1])
						gain = float(ln[2+self.options.gain_type])-self.agt
						if theta < 0 : 
							theta = -theta
							phi = (phi+540)
						phi = phi%360
						if abs(theta)==90 :
							fd.horizontal[phi]=gain
						if phi == 0:
							fd.vertical[theta]=gain
						if theta==90 and (abs(phi-angle)<=self.options.angle_step*.5) or theta==-90 and (abs(phi-180-angle)<=self.options.angle_step*.5):
							fd.gain = gain
							fd.angle = angle
						i = i+1
					except:
						break
			i = i+1
		if self.options.frequency_data:
			freqs = []
			for f in self.frequencies:
				if f.freq in self.options.frequency_data.keys():
					freqs.append(f)
			self.frequencies = freqs

class NecFileObject:
	def __init__(self, options):
		self.options = options
		self.vars = {}
		self.min_max = {}
		self.dependent_vars = []
		self.lines=[]
		self.varlines=[]
		self.paramlines={}
		self.source_tags={}
		self.autosegment=(0,0)
		self.frequency = 585
		self.scale = 1
		self.options.angle_step = 5
		if options.engine_takes_cmd_args=='yes' or options.engine_takes_cmd_args=='auto' and os.name!='nt':
			self.options.engine_takes_cmd_args = 1
		else: self.options.engine_takes_cmd_args = 0
		try:self.write_js_model = options.js_model
		except AttributeError: self.write_js_model=0
		if self.options.input:
			self.readSource(self.options.input)
			try:
				if self.options.param_values_file:
					self.parseParameterValues(self.options.param_values_file)
					self.writeParametrized("output.nec")
			except AttributeError:
				pass
		self.autoSegmentation(self.options.auto_segmentation)
		self.prepareSweeps()
		if self.options.debug:
			printOut( "Engine jobs:")
			pprint.pprint(self.sweeps)

	def readSource(self, sourcefile):
		if self.options.debug: sys.stderr.write("debug: Opening file %s\n"%sourcefile)
		self.options.input = sourcefile
		file = open(sourcefile, "rt")
		try: self.lines = file.readlines()
		finally: file.close()
		if not self.lines: raise "Empty input file"
		self.parse()
	
	def evalVarLine(self, line, g=None, l=None):
		ln = line.replace("^","**")
		if l is None:
			d={}
			exec(ln, {}, d)
			return d
		else:
			exec(ln, g, l)


	def parse(self):		
		if self.options.debug: sys.stderr.write("debug: Parsing input\n")
		self.vars = {}
		self.dependent_vars = []
		self.varlines=[]
		self.source_tags={}
		self.comments = []
		for i in range(len(self.lines)):
			ln = self.lines[i].strip('\n')
			comment_pos = ln.find("'")
			if comment_pos!=-1:
				comment = ln[comment_pos+1:].strip()
				ln = ln[0:comment_pos].strip()
			else:
				comment = ""
				ln = ln.strip()
			if ln[0:2]== "SY":
				if self.options.debug >1: sys.stderr.write("debug: \tParsing line: \"%s\"\n"%ln)
				try:
					d = self.evalVarLine(ln[3:].strip())
					if self.options.debug: 
						for dk in d.keys(): sys.stderr.write("debug: \tAdded independent parameter \"%s\"\n"%dk)
						if self.options.debug>1: sys.stderr.write("debug: \t\tFull comment = \"%s\"\n"%comment)
					self.vars.update(d)
					for dk in d.keys(): self.paramlines[dk]=i
					try:
						#strip the real comment from the comment
						comment_pos = comment.find("'")
						if comment_pos!=-1:
							comment = comment[0:comment_pos].strip()
						if self.options.debug>1: 
							sys.stderr.write("debug: \t\tLimits comment = \"%s\"\n"%comment)
						min, max = eval(comment)
						if min <= max:
							for dk in d.keys(): self.min_max[dk]=(float(min),float(max))
						else:
							for dk in d.keys(): self.min_max[dk]=(float(max),float(min))
						if self.options.debug: sys.stderr.write("debug: \t\tlimits(%.3g, %.3g)\n"%(float(min), float(max)))
					except:
						if self.options.debug>1: 
							for dk in d.keys(): sys.stderr.write("debug: \tNo limits found for parameter \"%s\"\n"%dk)
						pass
				except:
					if self.options.debug: sys.stderr.write("debug: \tAdded dependent parameter \"%s\"\n"%ln[3:].strip())
					self.dependent_vars.append(ln[3:].strip())
			else:
				self.varlines.append(ln.replace(',',' ').split())
				self.comments.append(comment);
				if ln[0:2]=="EX":
					tag = int(self.varlines[-1][2])
					if tag not in self.source_tags:
						self.source_tags[tag]=[(len(self.varlines)-1,i,3)]
					else:
						self.source_tags[tag].append((len(self.varlines)-1,i,3))
				if ln[0:2]=="TL" or ln[0:2]=="NT":
					tag = int(self.varlines[-1][1])
					if tag not in self.source_tags:
						self.source_tags[tag]=[(len(self.varlines)-1,i,2)]
					else:
						self.source_tags[tag].append((len(self.varlines)-1,i,2))
					tag = int(self.varlines[-1][3])
					if tag not in self.source_tags:
						self.source_tags[tag]=[(len(self.varlines)-1,i,4)]
					else:
						self.source_tags[tag].append((len(self.varlines)-1,i,4))
				elif ln[0:2] == "FR":
					self.frequency = float(self.varlines[-1][5])
				elif ln[0:2] == "GS":
					self.scale = float(self.varlines[-1][3])
				elif ln[0:2] == "RP":
					self.options.angle_step = float(self.varlines[-1][8])

		for i in self.vars.keys():
			self.vars[i]=float(self.vars[i])

	def parseParameterValues(self, file):
		try:
			f = open(file,"rt")
			lines = f.readlines()
			f.close()
		except:
			raise
		if len(lines)<2: raise  RuntimeError("invalid Parametes files")
		vars = lines[0].split()
		del lines[0]
		lines[0] = list(map(float, lines[0].split()))
		opt_vars = {}
		for i in range(len(vars)):
			if vars[i] not in self.vars: raise RuntimeError("invalid Parameter name")
			self.vars[vars[i]] = lines[0][i]


	def parseAgt(self, output):
		file = open(output, "rt")
		try : 
			lines = file.readlines()
		finally:
			file.close()
		i=len(lines)-1
		tests = "   AVERAGE POWER GAIN="
		testl = len(tests)
		while i >0:
			if lines[i][0:testl]==tests:
				return float(lines[i][testl+1:].strip().split()[0].lower())
			i=i-1
		return 1

	def calcLength(self, line):
		return self.scale*necmath.sqrt(necmath.pow(line[2]-line[5],2)+necmath.pow(line[3]-line[6],2)+necmath.pow(line[4]-line[7],2))

	def autoSegment(self, line):
		length = self.calcLength(line) 
		nsegs = length*self.autosegment[0]/self.autosegment[1]
		line[1] = max(int(nsegs+.5),1)
		tag = line[0]
		segs = line[1]
		if tag in self.source_tags:
			if segs > 2: segs+=2
			if segs % 2 == 0:
				segs+=1
			line[1]=segs
			for refln in self.source_tags[tag]:
				varline_no = refln[0]
				line_no = refln[1]
				token_no = refln[2]
				self.varlines[varline_no][token_no] = str(int(segs/2)+1)
				self.lines[line_no] = " ".join(self.varlines[varline_no])
		

	def autoSegmentation(self, segs_per_halfwave=0, freq = None):
		if not freq: freq = self.frequency
		if not freq: freq = 585
		halfwave = 150.0/freq
		self.autosegment = (segs_per_halfwave, halfwave)
		#printOut("Autosegmentation set at %d per %g (freq=%f)"%(segs_per_halfwave, halfwave, freq))
		
	def writeSource(self, filename):
		file = open(filename, "wt")
		try: file.writelines(self.lines)
		finally: file.close()
	
	def evalToken(self, x):
		return eval(x, necmath.__dict__,self.globals)

	def formatNumber(self, n, fixed_width=1):
		if type(n) == type(.1):
			if fixed_width:
				return "%.7f"%n
			else:
				return "%.6g"%n
		else:
			return str(n)
	
	def formatName(self, n):
		return "%8s"%n

	def testLineIntersection(self, tag1, tag2, line1, line2, r1, r2):
		if line1[0]==line2[0]:
			if line1[1]!=line2[1]:return 1
			else :	raise GeometryError("Overlapping lines (tag %d and tag %d, distance=%f)"%(tag1, tag2, 0))
		if line1[0]==line2[1]:
			if line1[1]!=line2[0]:return 1
			else :	raise GeometryError("Overlapping lines (tag %d and tag %d, distance=%f)"%(tag1, tag2, 0))
		if line1[1]==line2[0]:
			if line1[0]!=line2[1]:return 1
			else :	raise GeometryError("Overlapping lines (tag %d and tag %d, distance=%f)"%(tag1, tag2, 0))
		if line1[1]==line2[1]:
			if line1[0]!=line2[0]:return 1
			else :	raise GeometryError("Overlapping lines (tag %d and tag %d, distance=%f)"%(tag1, tag2, 0))
		#print "line1[0] = [%f, %f, %f]"%tuple(line1[0])
		#print "line1[1] = [%f, %f, %f]"%tuple(line1[1])
		#print "line2[0] = [%f, %f, %f]"%tuple(line2[0])
		#print "line2[1] = [%f, %f, %f]"%tuple(line2[1])
		v1 = v3sub(line1[1],line1[0])
		l = v3len(v1)
		if not l:
			raise GeometryError("Line with 0 length (tag %d)"%tag1)
		v1 = v3mul(1.0/l,v1)
		v2 = v3sub(line2[1],line2[0])
		l = v3len(v2)
		if not l:
			raise GeometryError("Line with 0 length (tag %d)"%tag2)
		v2 = v3mul(1.0/l,v2)
		n = v3unit(v3cross(v1,v2))
		#print "v1 = [%f, %f, %f]"%tuple(v1)
		#print "v2 = [%f, %f, %f]"%tuple(v2)
		#print "n  = [%f, %f, %f]"%tuple(n)
		if n[0]==0 and n[1]==0 and n[2]==0: #parallel
			v2 = v3sub(line2[1], line1[0])
			d = v3dot(v1,v2)
			pr = v3add(line1[0],v3mul(d, v1))
			pr = v3sub(line2[1],pr)
			pr = v3len(pr)
			if pr>r1+r2+self.options.min_wire_distance:
				return 1

			zerocount = 0
			v2 = v3sub(line2[0], line1[0])
			d = d * v3dot(v1,v2)
			if d < 0 :
				raise GeometryError("Overlapping lines (tag %d and tag %d, distance=%f)"%(tag1, tag2, pr))
			elif d == 0:
				zerocount = zerocount+1
			v2 = v3sub(line2[1], line1[1])
			d = v3dot(v1,v2)
			v2 = v3sub(line2[0], line1[1])
			d = d * v3dot(v1,v2)
			if d < 0 :
				raise GeometryError("Overlapping lines (tag %d and tag %d, distance=%f)"%(tag1, tag2, pr))
			elif d == 0:
				zerocount = zerocount+1

			v2 = v3sub(line1[1], line2[1])
			d = v3dot(v1,v2)
			v2 = v3sub(line1[0], line2[1])
			d = d * v3dot(v1,v2)
			if d < 0 :
				raise GeometryError("Overlapping lines (tag %d and tag %d, distance=%f)"%(tag1, tag2, pr))
			elif d == 0:
				zerocount = zerocount+1


			v2 = v3sub(line1[1], line2[0])
			d = v3dot(v1,v2)
			v2 = v3sub(line1[0], line2[0])
			d = d * v3dot(v1,v2)
			if d < 0 :
				raise GeometryError("Overlapping lines (tag %d and tag %d, distance=%f)"%(tag1, tag2, pr))
			elif d == 0:
				zerocount = zerocount+1

			if zerocount > 2 :
				raise GeometryError("Overlapping lines (tag %d and tag %d, distance=%f)"%(tag1, tag2, pr))

			return 1

		s = v3sub(line1[0], line2[0])
		#print "s  = [%f, %f, %f]"%tuple(s)
		d = v3dot(n, s)
		#print "plane line distance = %f"%d
		if abs(d) > r1+r2 + self.options.min_wire_distance: #infinite lines are far enough
			return 1

		m = v3mul(d, n)
		l20 = v3sub(line2[0],m)
		l21 = v3sub(line2[1],m)
		#line2 and line1 are now in one plane

		c1 = v3cross(v3unit(v3sub(l20,line1[0])),v1)
		#print "c1 = [%f, %f, %f]"%tuple(c1)
		c2 = v3cross(v3unit(v3sub(l21,line1[0])),v1)
		#print "c2 = [%f, %f, %f]"%tuple(c2)
		dot1 = v3dot(c1, n)*v3dot(c2, n)
		c3 = v3cross(v3unit(v3sub(line1[0],l20)),v2)
		#print "c3 = [%f, %f, %f]"%tuple(c3)
		c4 = v3cross(v3unit(v3sub(line1[1],l20)),v2)
		#print "c4 = [%f, %f, %f]"%tuple(c4)
		dot2 = v3dot(c3, n)*v3dot(c4, n)
		#print (dot1, dot2)
		if dot1 < 0 and dot2 < 0:
				raise GeometryError("Intersecting lines (tag %d and tag %d)"%(tag1, tag2))
		return 1
	def testLineIntersections(self, lines):
		nlines= len(lines)
		for i in range(nlines):
			for j in range(i+1,nlines):
				self.testLineIntersection(lines[i][0], lines[j][0], [lines[i][2:5],lines[i][5:8]], [lines[j][2:5],lines[j][5:8]], lines[i][8], lines[i][8])

		return 1

	def mirrorStructure(self, lines,comments, tincr, x,y,z):
		#print "mirroring"
		l = len(lines)
		for i in range(l):
			lines.append(list(lines[i]))
			comments.append(comments[i])
			if lines[l+i][0]:
				lines[l+i][0]=lines[i][0]+tincr
			if x:
				lines[l+i][2]=-lines[i][2]
				lines[l+i][5]=-lines[i][5]
			if y:
				lines[l+i][3]=-lines[i][3]
				lines[l+i][6]=-lines[i][6]
			if z:
				lines[l+i][4]=-lines[i][4]
				lines[l+i][7]=-lines[i][7]

	def moveStructure(self, lines, rng, tincr, rx, ry,rz, x,y,z):
		#print "moving %d lines, from %d to %d, incrementing tags with %d"%(rng[1]-rng[0],rng[0],rng[1],tincr)
		rx = necmath.pi*rx/180
		ry = necmath.pi*ry/180
		rz = necmath.pi*rz/180
		for i in range(rng[0], rng[1]):
			if lines[i][0]:
				lines[i][0]+=tincr
			s = lines[i][2:5]
			e = lines[i][5:8]
			if rx:
				v3rotx(rx, s)
				v3rotx(rx, e)
			if ry:
				v3roty(ry, s)
				v3roty(ry, e)
			if rz:
				v3rotz(rz, s)
				v3rotz(rz, e)
			s[0]+=x
			s[1]+=y
			s[2]+=z
			e[0]+=x
			e[1]+=y
			e[2]+=z
			lines[i][2:5]=s
			lines[i][5:8]=e

	def moveCopyStructure(self, lines,comments, tincr, new_structures, rx, ry,rz, x,y,z, from_tag):
		#print "moving %d lines, incrementing tags with %d, starting from tag %d"%(len(lines),tincr, from_tag)
		l = len(lines)
		rng = (0, l)
		if from_tag:
			for i in range(0,l):
				if lines[i][0]==from_tag:
					rng = (i,l)
					break
			if rng == (0,l) and lines[0][0]!=from_tag:
				return

		if not new_structures:
			self.moveStructure(lines, rng, tincr, rx,ry,rz,x,y,z)
			return

		while new_structures:
			new_structures = new_structures-1
			for i in range(rng[0],rng[1]):
				lines.append(list(lines[i]))
				comments.append(comments[i])

			rng = (l,len(lines))
			l = len(lines)
			self.moveStructure(lines, rng, tincr, rx,ry,rz,x,y,z)


	def rotateStructure(self, lines,comments, tincr, nstructures):
		if nstructures<=1:
			return
		self.moveCopyStructure(lines,comments, tincr, nstructures-1, 0, 0,360.0/nstructures, 0,0,0, 0)

	def necInputLines(self, skiptags=["FR", "XQ", "RP", "EN"]):
		lines=[]
		math_lines = []
		comments = []
		self.globals={}
		self.globals.update(self.vars)
		for d in self.dependent_vars:
			try: self.evalVarLine(d,necmath.__dict__, self.globals)
			except:
				traceback.print_exc()
				sys.stderr.write( "failed parsing '%s'\n"%(d))
				raise
		for li in range(len(self.varlines)):
			ln = self.varlines[li]
			comment = self.comments[li]
			if not ln: continue
			fn = lambda x:self.formatNumber(x,0)
			if ln[0].strip() != "GW":
				if ln[0].strip() not in skiptags:
					if ln[0].strip() != "CM":
						sline = list(map( self.evalToken , ln[1:]))
						sline = map(fn, sline)
						lines.append(ln[0]+" "+" ".join(sline))
					else:
						lines.append(" ".join(ln))
				if ln[0].strip() == "GX":
					i1 = int(self.evalToken(ln[1]))
					self.mirrorStructure(math_lines,comments, i1, int(ln[2][0]), int(ln[2][1]), int(ln[2][2]))
					if not "GX" in skiptags:
						lines[-1]="GX %d %s"%(i1,ln[2])
				elif ln[0].strip() == "GM":
					if len(ln) < 10:
						ln=ln+(10-len(ln))*[".0"]
					i1 = int(self.evalToken(ln[1]))
					i2 = int(self.evalToken(ln[2]))
					f3 = self.evalToken(ln[3])
					f4 = self.evalToken(ln[4])
					f5 = self.evalToken(ln[5])
					f6 = self.evalToken(ln[6])
					f7 = self.evalToken(ln[7])
					f8 = self.evalToken(ln[8])
					i9 = int(self.evalToken(ln[9]))
					self.moveCopyStructure(math_lines,comments, i1, i2, f3, f4, f5, f6, f7, f8, i9)
					if not "GM" in skiptags:
						lines[-1]="GM %d %d %f %f %f %f %f %f %d"%(i1, i2, f3, f4, f5, f6, f7, f8, i9)
				elif ln[0].strip() == "GR":
					i1 = int(self.evalToken(ln[1]))
					i2 = int(self.evalToken(ln[2]))
					self.rotateStructure(math_lines,comments, i1, i2)
					if not "GR" in skiptags:
						lines[-1]="GR %d %d"%(i1, i2)
				elif ln[0].strip() == "SP":
					i1 = int(ln[1])
					i2 = int(self.evalToken(ln[2]))
					if not "SP" in skiptags:
						lines[-1]="SP %d %d "%(i1, i2)+" ".join(list(map( fn, map( self.evalToken , ln[3:]))))
				elif ln[0].strip() == "SM":
					i1 = int(self.evalToken(ln[1]))
					i2 = int(self.evalToken(ln[2]))
					if not "SM" in skiptags:
						lines[-1]="SM %d %d "%(i1, i2)+" ".join(list(map( fn, map( self.evalToken , ln[3:]))))
				elif ln[0].strip() == "SC":
					i1 = int(ln[1])
					i2 = int(ln[2])
					if not "SC" in skiptags:
						lines[-1]="SC %d %d "%(i1, i2)+" ".join(list(map( fn, map( self.evalToken , ln[3:]))))
			else:
				sline = list(map( self.evalToken , ln[1:]))
				math_lines.append(sline)
				comments.append(comment)
				if self.autosegment[0]:
					self.autoSegment(sline)
				sline = map(fn, sline)
				lines.append(ln[0]+" "+" ".join(sline))
		#del self.globals
		if self.write_js_model:
			self.writeJSModel(math_lines,comments)
		if not self.testLineIntersections(math_lines):
			return []
		return lines

	def writeJSModel(self, lines, comments):
		z = zip(comments,lines)
		z.sort()
		printOut( "var structure = [[")
		if not z:
			printOut("]]")
			return;
		c = z[0][0].strip()
		printOut( '"%s"'%c)
		for i in z:
			if i[0].strip() != c:
				c = i[0].strip()
				printOut( '], ["%s"'%c)
			ln = i[1]
			printOut( (",%.4f"*6) % tuple(ln[2:8]))
		printOut( "]]")

	def writeNecInput(self, filename, extralines=[], skiptags=[]):
		lines = self.necInputLines(skiptags)
		if not lines: return 0
		lines.extend(extralines)
		file = open(filename, "wt")
		try: file.write("\n".join(lines)+"\n")
		finally: file.close()
		return 1


	def writeParametrized(self, filename, extralines=[], skiptags=[], comments=[]):
		lines=[]
		self.globals={}
		self.globals.update(self.vars)
		for v in self.vars.keys():
			lno = self.paramlines[v]
			if v in self.min_max.keys():
				self.lines[lno] = "SY %s=%.7g ' %g, %g" %(v, self.vars[v], self.min_max[v][0], self.min_max[v][1])
			else:
				self.lines[lno] = "SY %s=%.7g" %(v, self.vars[v])
		for d in self.dependent_vars:
			try: self.evalVarLine(d, necmath.__dict__, self.globals)
			except:
				traceback.print_exc()
				sys.stderr.write("failed parsing '%s'\n"%(d))
				raise
		has_comments = 0
		for ln in self.lines:
			comment_pos = ln.find("'")
			if comment_pos!=-1:
				comment = ln[comment_pos:].strip('\n')
				ln = ln[0:comment_pos].strip(' ')
			else:
				comment = ""
				ln = ln.strip(' ')
			sl = ln.replace(',',' ').split()
			if sl and sl[0].strip() == "CE":
				has_comments=1
			if not sl or not self.autosegment[0] or sl[0].strip() != "GW" : 
				lines.append(ln.strip()+comment)
				continue
			if sl[0].strip() == "GW":
				sline = list(map( self.evalToken , sl[1:]))
				self.autoSegment(sline)
				sl[2] = str(sline[1])
				lines.append(" ".join(sl)+comment)

		#del self.globals
		lines.extend(extralines)
		file = open(filename, "wt")
		try: 
			if comments:
				file.write("CM ")
				file.write("\nCM ".join(comments))
				file.write("\n")
				if not has_comments:
					file.write("CE\n")
			file.write("\n".join(lines)+"\n")
		finally: file.close()

	def freqSweepLines(self, nec_input_lines, sweep):
		lines = list(nec_input_lines)
		ranges = sweep.ranges
		angles = sweep.angles
		frequency_data = self.options.frequency_data
		angle_sweep = not self.options.frequency_data and not self.options.forward
		if self.options.calc.gain:
			for i in range(len(ranges)):
				lines.append("FR 0 %d 0 0 %g %g"%(ranges[i][2],ranges[i][0],ranges[i][1]))
				if not angle_sweep:
					lines.append("RP 0 1 1 1000 90 %g 0 0"%angles[i])
				else: 
					lines.append("RP 0 1 %d 1000 90 %g 0 %g"%(int(360/self.options.angle_step)+1, angles[i], self.options.angle_step))
		else:
			lines.append("FR 0 %d 0 0 %g %g"%(ranges[0][2],ranges[0][0],ranges[0][1]))
			lines.append("PQ -1")
			lines.append("PT -1")
		lines.append("XQ")
		lines.append("EN")
		return lines
#		self.writeNecInput(filename, lines, ["FR", "XQ", "RP", "EN"])
	def agtLines(self, nec_input_lines, sweep):
		lines = []
		for line in nec_input_lines:
			if line[0:2]!="LD":
				lines.append(line)
		agt_freq = sweep.agt_freq
		lines.append("FR 0 0 0 0 %g 0"%agt_freq)
		step = self.options.angle_step
		if step < 5 and self.options.forward:
			step = 5
		hcount = int(360/step)+1
		vcount = int(180/step)+1
		#lines.append("RP 0 %d %d 1001 -180 0  %g %g"%(vcount, hcount, step, step))
		lines.append("RP 0 %d %d 1001 -180 %g  %g %g"%(vcount, hcount, self.options.forward_dir, step, step))
		lines.append("XQ")
		lines.append("EN")
		return lines
	
	def runSweep(self, nec_input_lines, sweep, get_agt_scores=0, use_agt = None, id=""):
		#print "Get agt score = %d"%get_agt_scores
		#import tempfile as tmp
		import subprocess as sp
		import os
		try:
			os.mkdir(self.options.output)
		except : pass
			
		nec_input = os.path.join(".",self.options.output,"nec2_"+id+".inp")
		agt_input = nec_input[0:-3]+"agt"

		file = open(nec_input, "wt")
		fslines = self.freqSweepLines(nec_input_lines,sweep)
		if not fslines:
			return ()
		try: file.write("\n".join(fslines))
		finally: file.close()
		if (self.options.agt_correction or get_agt_scores) and (use_agt is None):
			file = open(agt_input, "wt")
			try: file.write("\n".join(self.agtLines(nec_input_lines,sweep)))
			finally: file.close()
		
		nec_output = nec_input[0:-3]+"out"
		exe_input = nec_input[0:-3]+"cin"
		agt = 1.0
		if use_agt is not None:
			agt = use_agt
		elif self.options.agt_correction or get_agt_scores :
			if self.options.engine_takes_cmd_args:
				popen = sp.Popen([self.options.engine, agt_input, nec_output] )
				popen.wait()
			else:
				try:
					f = open(exe_input,"wt")
					f.write(agt_input)
					f.write("\n")
					f.write(nec_output)
					f.write("\n")
					f.close()
					f = open(exe_input)
					popen = sp.Popen(self.options.engine, stdin=f, stdout=open(os.devnull, "w"))
					popen.wait()
				finally:
					f.close()
			agt = self.parseAgt(nec_output)
			if get_agt_scores:
				return (nec_output,agt)
		if self.options.engine_takes_cmd_args:
			popen = sp.Popen([self.options.engine, nec_input, nec_output] )
			popen.wait()
		else:
			try:
				f = open(exe_input,"wt")
				f.write(nec_input)
				f.write("\n")
				f.write(nec_output)
				f.write("\n")
				f.close()
				f = open(exe_input)
				popen = sp.Popen(self.options.engine, stdin=f, stdout=open(os.devnull, "w"))
				popen.wait()
			finally:
				f.close()
		return (nec_output,agt)
		
	def runSweepT(self, nec_input_lines, sweep, number, result_map, result_lock, get_agt_scores=0, use_agt = None, id=0 ):
		r = None
		try:
			ua = None
			if use_agt and number in use_agt:
				ua = use_agt[number]
			r = self.runSweep(nec_input_lines,sweep, get_agt_scores,ua, str(id)+"_"+str(number))
		except KeyboardInterrupt:
			raise
		except:
			try:
				result_lock.acquire()
				traceback.print_exc()
			finally:
				result_lock.release()

			return
		result_lock.acquire()
		try: 
			if r : result_map[number]=(r[0],sweep.sweepid,r[1], number)
		finally: result_lock.release()

	def prepareSweeps(self):
		total_freqs = len(self.options.frequency_data)
		num_cores = self.options.num_cores
		sweeps = self.options.sweeps
		if not total_freqs: 
			for i in sweeps: 
				total_freqs = total_freqs+i[2]
		self.sweeps = []
		if not total_freqs: 
			return self.sweeps
		if total_freqs < num_cores : 
			num_cores = total_freqs
		freqs_per_core = (total_freqs+.0)/num_cores
		
		freqs_per_sweep = [0]*len(sweeps)
		if self.options.frequency_data:
			for f in self.options.frequency_data.keys():
				for s in range(len(sweeps)):
					sw = sweeps[s]
					if f>=sw[0] and f <=sw[0]+sw[1]*sw[2]:
						freqs_per_sweep[s]+=1
						break
		else:
			for s in range(len(sweeps)):
				freqs_per_sweep[s] = sweeps[s][2]

		i=len(sweeps)
		while i:
			i-=1
			if not freqs_per_sweep[i]:
				del freqs_per_sweep[i]
				del sweeps[i]

		
		cores_per_sweep = [0]*len(sweeps)
		while num_cores:
			for i in range(len(sweeps)):
				if cores_per_sweep[i]: continue
				if freqs_per_sweep[i] < freqs_per_core:
					cores_per_sweep[i] =  1 
					total_freqs = total_freqs - freqs_per_sweep[i]
					num_cores = num_cores-1
					if not num_cores: break
				else:
					cores_per_sweep[i] = 0 
		
			if not num_cores:
				for i in range(len(sweeps)):
					if cores_per_sweep[i]: continue
					cores_per_sweep[i] = 1
				break
			if freqs_per_core == (total_freqs+.0)/num_cores:
				smallest = -1
				smallest_count = total_freqs+1
				for i in range(len(sweeps)):
					if cores_per_sweep[i]: continue
					if freqs_per_sweep[i] < smallest_count:
						smallest_count = freqs_per_sweep[i]
						smallest = i
						
				cores_per_sweep[smallest] = min(num_cores, round(freqs_per_sweep[smallest]/freqs_per_core) )
				num_cores = num_cores-cores_per_sweep[smallest]
				total_freqs = total_freqs - freqs_per_sweep[smallest]

			if not num_cores or not total_freqs: break
			freqs_per_core = (total_freqs+.0)/num_cores

		for i in range(len(sweeps)):
			self.appendSweep(sweeps[i],cores_per_sweep[i],freqs_per_sweep[i], i)

	def appendSweep(self, sweep, num_cores, sweep_size,sweepid):
		sweep_freqs = []
		angles = []
		while num_cores:
			num_freqs = int(sweep_size/num_cores)
			if not self.options.frequency_data:
				half = int(num_freqs / 2)
				self.sweeps.append(Sweep( [(sweep[0],sweep[1],num_freqs)],[self.options.forward_dir],sweep[0]+half*sweep[1],sweepid))
			else:
				if not sweep_freqs:
					freqs = sorted(self.options.frequency_data.keys())
					for freq in freqs:
						if freq >= sweep[0] and freq <= sweep[0]+sweep[1]*sweep[2]:
							sweep_freqs.append(freq)
							angles.append(self.options.frequency_data[freq][0])

				if num_freqs == 1:
					self.sweeps.append(Sweep( [(sweep_freqs[0],0,1)], [angles[0]], sweep_freqs[0],sweepid))
					del sweep_freqs[0]
					del angles[0]
				elif num_freqs == 2:
					self.sweeps.append(Sweep( [(sweep_freqs[0],0,1), (sweep_freqs[1],0,1)], angles[0:2], sweep_freqs[0],sweepid))
					del sweep_freqs[0:2]
					del angles[0:2]
				else:
					freqs = sorted(sweep_freqs[0:num_freqs])
					mid_freq = (sweep_freqs[num_freqs-1]+sweep_freqs[0])/2
					agt_index = 0
					for i in range(1,num_freqs):
						if abs(sweep_freqs[i]-mid_freq) < abs(sweep_freqs[agt_index]-mid_freq):
							agt_index = i
					self.sweeps.append(Sweep( [(sweep_freqs[i],0,1) for i in range(num_freqs)], angles[0:num_freqs], sweep_freqs[agt_index],sweepid))
					del sweep_freqs[0:num_freqs]
					del angles[0:num_freqs]


			sweep = (sweep[0]+num_freqs*sweep[1],sweep[1],sweep[2]-num_freqs)
			num_cores = num_cores-1
			sweep_size-=num_freqs

	def cleanupOutput(self, older_than = 10):
		import os, time, stat
		try:
			ldir = os.listdir(self.options.output)
			now = time.time()
			for f in ldir:
				try:
					f = os.path.join(self.options.output,f)
					s = os.stat(f)
					if s[stat.ST_MTIME] + older_than < now:
						os.remove(f)
				except:
					pass
		except:
			pass


	def runSweeps(self, get_agt_scores = 0, use_agt = None, id = ""):
		#if self.options.cleanup:
		#	self.cleanupOutput(self.options.cleanup)
		results={}
		number=0
		try:
			nec_input_lines = self.necInputLines()
		except:
			if not self.options.quiet: traceback.print_exc()
			return

		from threading import Lock, Thread
		result_lock = Lock()
		threads = []
		for i in range(len(self.sweeps)-1):
			sweep = self.sweeps[i]
			threads.append(Thread(target=self.runSweepT, args=(nec_input_lines, sweep, number,results, result_lock,get_agt_scores,use_agt,id )))
			threads[-1].start()
			number = number+1

		r = None
		sweep = self.sweeps[-1]
		try:
			ua = None
			if use_agt and number in use_agt:
				ua = use_agt[number]
			r = self.runSweep(nec_input_lines,sweep, get_agt_scores,ua, str(id)+"_"+str(number))
		except KeyboardInterrupt:
			raise
		except:
			traceback.print_exc()
		for t in threads:
			t.join()
		#after the joins so we dont have to lock
		if r : results[number]=(r[0],sweep.sweepid,r[1], number)
			

		r = []
		for i in results.keys():
			r.append(results[i])
		return r


	def evaluate(self, chart_like=0):
		NOP = NecOutputParser 
		results = self.runSweeps() #[[174,6,8],[470,6,40]]
		h={}
		v={}
		if not chart_like:
			printOut("Input file : %s"%self.options.input )
			printOut("Freq sweeps: %s"%str(self.options.sweeps) )
			if self.autosegment[0]:
				printOut("Autosegmentation: %d per %g"%self.autosegment)
			else:
				printOut("Autosegmentation: NO")
			printOut("\n")
	
			for r in range(len(results)):
				nop = NOP(results[r][0], results[r][2], self.options)
				if self.options.debug > 1:
					for f in nop.frequencies:
						printOut(f.horizontal)
				h.update(nop.horizontalPattern())
				v.update(nop.verticalPattern())
				nop.printFreqs(r==0)
		else:
			res = [];
			for r in range(len(results)):
				nop = NOP(results[r][0], results[r][2], self.options)
				h.update(nop.horizontalPattern())
				v.update(nop.verticalPattern())
				res = res+nop.getGainSWRChartData()
			res.sort()
			g = self.options.input+"_gain"
			for i in res: g+=(",%.2f"%i[1])
			s = self.options.input+"_swr"
			for i in res: s+=(",%.2f"%i[2])
			printOut( g)
			printOut( s)

		if self.write_js_model:
			printOut( "Horizontal:")
			printOut( sorted(h.keys()))
			for i in sorted(h.keys()):
				l = int(len(h[i])/2)+1;
				printOut( "["+("%.2f,"*l)[0:-1]%tuple(h[i][0:l])+"],")

			printOut( "Vertical:")
			printOut( sorted(v.keys()))
			for i in sorted(v.keys()):
				l = int(len(v[i])/2)+1;
				printOut( "["+("%.2f,"*l)[0:-1]%tuple(v[i][0:l])+"],")
				


import optparse 
class OptionParser(optparse.OptionParser):
	def __init__(self):
		optparse.OptionParser.__init__(self)
		self.add_option("-o", "--output-dir", type="string", metavar="DIR", dest="output", default=output, help="output path [%default]")
		self.add_option("-i", "--input", type="string", metavar="NEC_FILE", dest="input", default="", help="input nec file")
		self.add_option("-s", "--sweep", type="string", metavar="SWEEP", action="append", dest="sweeps", help="adds a sweep range e.g. -s (174,6,8) for vhf-hi freqs")
		self.add_option("-C", "--char-impedance", type="float", metavar="IMPEDANCE", default=300.0, help="The default is %default Ohms.")
		self.add_option("-u", "--uhf", "--uhf-52", action="append_const", dest="sweeps", const="(470,6,39)", help="adds a uhf (ch. 14-51) sweep")
		self.add_option("-U", "--uhf-69", action="append_const", dest="sweeps", const="(470,6,57)", help="adds a uhf (ch. 14-69) sweep")
		self.add_option("-V", "--vhf-hi", action="append_const", dest="sweeps", const="(174,6,8)", help="adds a vhf-hi (ch. 7-13) sweep")
		self.add_option("-v", "--vhf-lo", action="append_const", dest="sweeps", const="(54,6,6)", help="adds a vhf-lo (ch. 1-6) sweep")
		self.add_option("-n", "--num-cores", type="int", default=ncores, help="number of cores to be used, default=%default")
		self.add_option("-a", "--auto-segmentation", metavar="NUM_SEGMENTS", type="int", default=autosegmentation, help="autosegmentation level - set to 0 to turn autosegmentation off, default=%default")
		self.add_option("-e", "--engine", metavar="NEC_ENGINE", default="nec2dxs1k5", help="nec engine file name, default=%default")
		self.add_option("--engine-takes-cmd-args", default="auto", type="string", help="the nec engine takes command args, default=auto (which means no on windows yes otherwise). Other options are 'yes' or 'no'.")
		self.add_option("-d", "--min-wire-distance", default=.005, type="float", help="minimum surface-to-surface distance allowed between non-connecting wires, default=%default")
		self.add_option("--debug", default=0, type="int", help="turn on some loging")
		self.add_option("--forward-dir", default=0, type="int", help="the forward direction, by default is 0 which means the antenna forward is along X.")
		self.add_option("--backward-dir", default=180, type="int", help="the backward direction (relative to --forward-dir) to which F/R and F/B are calculated. The default is 180 which means the exact opposite of the forward-dir")
		self.add_option("--rear-angle", default=120, type="int", help="angle for calculating rear gain (max 270)")
		self.set_defaults(gain_type=1)
		self.add_option("--vertical-gain", action="store_const", const=0, dest="gain_type", help="calculate horizontal gain [default]")
		self.add_option("--horizontal-gain", action="store_const", const=1, dest="gain_type", help="calculate vertical gain")
		self.add_option("--total-gain", action="store_const", const=2, dest="gain_type", help="calculate total gain")
		self.add_option("-f", "--frequency_data", default = "{}", help="a map of frequency to (angle, expected_gain) tuple" )
		self.add_option("--cleanup", default=180, type="int", help="remove output files older than CLEANUP seconds. set to 0 to disable")
	def parse_args(self):
		options, args = optparse.OptionParser.parse_args(self)
		if options.rear_angle<0 or options.rear_angle>270: raise ValueError("Invalid rear angle of %d"%options.rear_angle)
		options.frequency_data = eval(options.frequency_data)
		if options.input == "":
			if len(args):
				options.input=args[0]
				del args[0]
			else:
				options.input = input
		while options.forward_dir < 0:
			options.forward_dir+=360
		while options.forward_dir > 360:
			options.forward_dir-=360
		options.backward_dir += options.forward_dir
		while options.backward_dir < 0:
			options.backward_dir+=360
		while options.backward_dir > 360:
			options.backward_dir-=360
		if options.sweeps:
			options.sweeps = list(map(eval,options.sweeps))
		return (options, args)

def optionParser():
	class MainOptionParser(OptionParser):
		def __init__(self):
			OptionParser.__init__(self)
			self.add_option("--param-values-file", default="", help="Read the parameter values from file, generate output.nec and evaluate it instead of the input file. The file should contain two lines: space separated parameter names on the first and space separated values on the second.")
			self.add_option("--agt-correction", default=1, type="int", help="ignored. agt correction is always applied")
			self.add_option("-c", "--centers", default=True, help="run sweep on the channel centers",action="store_false", dest="ends")
			self.add_option("--chart", default=0, action="store_true")
			self.add_option("--js-model", default=0, action="store_true", help="write jsmodel")
		def parse_args(self):
			options, args = OptionParser.parse_args(self)
			class Calc: pass
			options.calc = Calc()
			options.calc.gain=1
			options.calc.f2b=1
			options.calc.f2r=1
			options.quiet=0
			options.forward = 0
			options.verbose=0
			if not options.sweeps:
				options.sweeps = [(470,6,39)]
			if not options.ends:
				for i in range(len(options.sweeps)):
					if not options.sweeps[i][1]: continue
					options.sweeps[i] = (options.sweeps[i][0] - options.sweeps[i][1]/2, options.sweeps[i][1], options.sweeps[i][2]+1)
			return (options, args)
	return MainOptionParser()


def run(options):
	nf = NecFileObject(options)
	nf.evaluate(options.chart)

def main():
#default values
	options, args = optionParser().parse_args()
	run(options)
	for inp in args:
		if inp[0]!="-":
			options.input = inp
			try:
				run(options)
			except:
				traceback.print_exc()
				pass
	


if __name__ == "__main__":
	main()
