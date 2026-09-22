import asyncio, subprocess, wave, json
from pathlib import Path
import edge_tts, imageio_ffmpeg
P=Path(__file__).resolve().parent
lines=[
'Running a business means keeping track of a hundred moving parts. Your stock should not be another mystery.',
'Meet Stocklist by M C C I A. One workspace for your stock, purchases, and sales.',
'See what is available. Record incoming and outgoing stock. Spot low stock items before they interrupt your day.',
'Manage purchases, track customer orders, and create sales invoices. Know what is received, dispatched, and still pending.',
'Give your team access for their roles. Use clear reports to understand where your business stands.',
'Try Stocklist with ready to use sample data. Know your stock. Keep business moving.'
]
async def main():
    voices=await edge_tts.list_voices()
    candidates=[v for v in voices if v['Locale']=='en-IN' and v['Gender']=='Female']
    if not candidates: raise RuntimeError('No Indian English female voice available')
    chosen=next((v for v in candidates if v['ShortName']=='en-IN-NeerjaNeural'),candidates[0])['ShortName']
    print('Voice:',chosen,flush=True)
    for i,line in enumerate(lines):
        await edge_tts.Communicate(line,chosen,rate='+0%').save(str(P/f'indian_voice_{i}.mp3'))
        print('Narration ready:',i+1,flush=True)
    (P/'indian_voice_metadata.json').write_text(json.dumps({'voice':chosen,'lines':lines},indent=2))
asyncio.run(main())
ff=imageio_ffmpeg.get_ffmpeg_exe()
durations=[8,8,12,12,10,10]
args=[ff,'-y','-loglevel','error','-i',str(P/'picture.mp4')]
filters=[]
for i,slot in enumerate(durations):
    source=P/f'indian_voice_{i}.mp3'; wav=P/f'indian_voice_{i}.wav'
    subprocess.run([ff,'-y','-loglevel','error','-i',str(source),str(wav)],check=True)
    with wave.open(str(wav)) as w: duration=w.getnframes()/w.getframerate()
    tempo=max(1,duration/(slot-.7))
    print('Scene',i+1,'speech seconds',round(duration,2),'tempo',round(tempo,3),flush=True)
    args+=['-i',str(source)]
    filters.append(f'[{i+1}:a]aresample=48000,atempo={tempo},adelay=350,apad,atrim=duration={slot}[v{i}]')
args+=['-i',str(P/'music.wav')]
filters+=[''.join(f'[v{i}]' for i in range(6))+'concat=n=6:v=0:a=1,loudnorm=I=-17:TP=-2:LRA=9[voice]','[voice][7:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]']
args+=['-filter_complex',';'.join(filters),'-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k','-t','60','-movflags','+faststart',str(P/'Stocklist_MCCIA_Indian_English_60s.mp4')]
subprocess.run(args,check=True)
print('EXPORT COMPLETE',flush=True)
