from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import subprocess, wave, math
import numpy as np
import imageio_ffmpeg

P=Path(__file__).resolve().parent
ROOT=P.parents[1]
FF=imageio_ffmpeg.get_ffmpeg_exe()
W,H=1920,1080
NAVY='#102E43'; BLUE='#216FA5'; GREEN='#219B51'; CREAM='#F5F8FA'
fontdir=Path('C:/Windows/Fonts')
def font(n,bold=False): return ImageFont.truetype(str(fontdir/('segoeuib.ttf' if bold else 'segoeui.ttf')),n)
def txt(d,xy,s,size=40,fill=NAVY,bold=False): d.text(xy,s,font=font(size,bold),fill=fill,spacing=16)
logo=Image.open(ROOT/'static/branding/logo-mccia-white-blue-new.png').convert('RGBA')
logo.thumbnail((230,85))
shots=[
 (8,'YOUR EVERYDAY BUSINESS','Too many\nmoving parts.',None,'Stock. Purchases. Sales.\nBring the picture together.'),
 (8,'MEET STOCKLIST','Your business.\nIn view.','overview','One workspace for stock, purchases and sales.'),
 (12,'01 / STOCK','Know what\nyou have.','products','Available stock  /  Incoming quantities  /  Reorder levels'),
 (6,'02 / PURCHASES','Keep purchases\nmoving.','purchases','Draft. Review. Approve. Receive.'),
 (6,'03 / SALES','Stay on top\nof sales.','sales','Customer orders  /  Invoices  /  Pending payments'),
 (10,'04 / YOUR TEAM','Clarity for\nevery role.','reports','Owner  /  Warehouse  /  Accountant  /  Read-only'),
 (10,'STOCKLIST BY MCCIA','Know your stock.\nKeep business moving.',None,'Explore the demo')]
for i,(duration,kicker,title,screen,footer) in enumerate(shots):
 im=Image.new('RGB',(W,H),CREAM); d=ImageDraw.Draw(im)
 d.rectangle((0,0,W,12),fill=BLUE); d.rectangle((W-460,0,W,12),fill=GREEN)
 im.paste(logo,(80,55),logo)
 txt(d,(1520,72),'STOCKLIST',30,BLUE,True)
 if screen:
  txt(d,(80,205),kicker,24,BLUE,True)
  txt(d,(80,292),title,64,NAVY,True)
  d.rounded_rectangle((80,545,205,552),radius=3,fill=GREEN)
  txt(d,(80,600),'Less guesswork.\nMore visibility.',27,'#567080')
  d.rounded_rectangle((560,191,1840,935),radius=24,fill='#DDE6ED')
  shot=Image.open(P/(screen+'.png')).convert('RGB').resize((1240,698),Image.Resampling.LANCZOS)
  im.paste(shot,(580,210))
  txt(d,(580,951),footer,27,BLUE)
 else:
  txt(d,(80,210),kicker,28,BLUE,True)
  txt(d,(80,295),title,100,NAVY,True)
  if i==0:
   for j,(word,small) in enumerate([('STOCK','What is available?'),('PURCHASES','What is arriving?'),('SALES','What is pending?')]):
    x=80+j*585
    d.rounded_rectangle((x,645,x+545,870),radius=24,fill='white',outline='#DAE4EA',width=2)
    txt(d,(x+35,680),word,30,BLUE,True); txt(d,(x+35,755),small,37,NAVY)
   txt(d,(80,930),'Bring the picture together.',36,GREEN,True)
  else:
   d.rounded_rectangle((80,620,575,722),radius=16,fill=GREEN)
   txt(d,(117,642),'Explore the demo  →',40,'white',True)
   txt(d,(80,785),'Sample data. No business credentials needed.',34,NAVY)
   txt(d,(80,855),'A separate, temporary workspace for every visitor.',30,'#567080')
   txt(d,(80,966),'STOCK  /  PURCHASES  /  SALES',25,BLUE,True)
 d.line((80,1025,1840,1025),fill='#D5E0E7',width=2)
 txt(d,(80,1040),'MCCIA  •  Tools for growing businesses',18,'#567080')
 txt(d,(1740,1040),f'{i+1:02d} / 07',18,'#567080')
 im.save(P/f'card_{i}.png')
 print('Rendering scene',i+1,flush=True)
 filt=f"zoompan=z='1+0.012*on/{duration*24}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1920x1080:fps=24,fade=t=in:st=0:d=0.3,fade=t=out:st={duration-0.3}:d=0.3,format=yuv420p"
 subprocess.run([FF,'-y','-loglevel','error','-loop','1','-framerate','24','-i',str(P/f'card_{i}.png'),'-vf',filt,'-t',str(duration),'-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-an',str(P/f'scene_{i}.mp4')],check=True)
(P/'scenes.txt').write_text(''.join(f"file 'scene_{i}.mp4'\n" for i in range(7)))
subprocess.run([FF,'-y','-loglevel','error','-f','concat','-safe','0','-i',str(P/'scenes.txt'),'-c','copy',str(P/'picture.mp4')],check=True)
# Original, understated instrumental bed: soft chord pulses and a sparse melody.
sr=48000; music=np.zeros(sr*60,dtype=np.float64)
chords=[(130.81,164.81,196),(110,130.81,164.81),(87.31,110,130.81),(98,123.47,146.83)]
for beat in range(120):
 start=int(beat*.5*sr); t=np.arange(min(sr, len(music)-start))/sr
 chord=chords[(beat//8)%4]
 for freq in chord:
  music[start:start+len(t)]+=.009*np.sin(2*np.pi*freq*t)*np.exp(-3.5*t)*np.minimum(t*50,1)
 if beat%2==0:
  freq=chord[(beat//2)%3]*4
  music[start:start+len(t)]+=.012*np.sin(2*np.pi*freq*t)*np.exp(-5*t)*np.minimum(t*100,1)
 music[start:start+len(t)]+=.013*np.sin(2*np.pi*55*t)*np.exp(-20*t)
music*=np.minimum(np.arange(len(music))/sr/2,1)*np.minimum((len(music)-np.arange(len(music)))/sr/3,1)
with wave.open(str(P/'music.wav'),'wb') as f:
 f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr); f.writeframes((music*32767).astype('<i2').tobytes())
args=[FF,'-y','-loglevel','error','-i',str(P/'picture.mp4')]
for i in range(6):args+=['-i',str(P/f'voice_{i}.wav')]
args+=['-i',str(P/'music.wav')]
durations=[8,8,12,12,10,10]
filters=[f'[{i+1}:a]aresample=48000,adelay=400,apad,atrim=duration={dur}[v{i}]' for i,dur in enumerate(durations)]
filters+=[''.join(f'[v{i}]' for i in range(6))+'concat=n=6:v=0:a=1[voice]','[voice][7:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]']
args+=['-filter_complex',';'.join(filters),'-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k','-t','60','-movflags','+faststart',str(P/'Stocklist_MCCIA_60s_Trailer.mp4')]
subprocess.run(args,check=True)
print('TRAILER COMPLETE',flush=True)
