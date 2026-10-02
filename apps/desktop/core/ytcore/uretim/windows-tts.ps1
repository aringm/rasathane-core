param([Parameter(Mandatory=$true)][string]$InputPath, [Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$taskInput = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
# Windows OneCore sesleri eski SAPI listesinde görünmeyebilir. Windows 10+
# WinRT API'si bunları registry yazmadan kullanır.
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime]
$winVoice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object Language -eq 'tr-TR' | Select-Object -First 1
if ($winVoice) {
    $winSpeech = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
    try {
        $winSpeech.Voice = $winVoice
        $operation = $winSpeech.SynthesizeTextToStreamAsync([string]$taskInput.metin)
        $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
        $task = $asTask.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke($null, @($operation))
        $stream = $task.GetAwaiter().GetResult()
        $readStream = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
        $writeStream = [System.IO.File]::Create($OutputPath)
        try { $readStream.CopyTo($writeStream) } finally { $writeStream.Dispose(); $readStream.Dispose(); $stream.Dispose() }
    } finally { $winSpeech.Dispose() }
    exit 0
}
$speech = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $speech.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'tr-TR' } | Select-Object -First 1
    if (-not $voice) { throw 'Türkçe Windows sesi kurulu değil. Windows Dil ve Konuşma ayarlarından Türkçe ses paketini kurun.' }
    $speech.SelectVoice($voice.VoiceInfo.Name)
    $speech.SetOutputToWaveFile($OutputPath)
    $speech.Speak([string]$taskInput.metin)
    $speech.SetOutputToNull()
} finally { $speech.Dispose() }
