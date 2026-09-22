$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice.SelectVoice('Microsoft Zira Desktop')
$voice.Rate = 0
$lines = @(
'Running a business means keeping track of a hundred moving parts. Your stock should not be another mystery.',
'Meet Stocklist by MCCIA. One workspace for your stock, purchases, and sales.',
'See what is available. Record incoming and outgoing stock. Spot low stock items before they interrupt your day.',
'Manage purchases, track customer orders, and create sales invoices. Know what is received, dispatched, and still pending.',
'Give your team access for their roles. Use clear reports to understand where your business stands.',
'Try Stocklist with ready to use sample data. Know your stock. Keep business moving.'
)
for ($i=0; $i -lt $lines.Count; $i++) {
 $voice.SetOutputToWaveFile((Join-Path (Get-Location) "output/trailer/voice_$i.wav"))
 $voice.Speak($lines[$i])
 $voice.SetOutputToNull()
}
$voice.Dispose()
