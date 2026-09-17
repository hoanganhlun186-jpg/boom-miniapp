param([Parameter(Mandatory=$true)][string]$Payload,[Parameter(Mandatory=$true)][string]$Key,[Parameter(Mandatory=$true)][string]$Signature)
$ErrorActionPreference='Stop'
$rsaBoom = New-Object System.Security.Cryptography.RSACryptoServiceProvider
$rsaBoom.PersistKeyInCsp=$false
try {
  $rsaBoom.FromXmlString([IO.File]::ReadAllText($Key))
  $bytesBoom=[IO.File]::ReadAllBytes($Payload)
  $signedBoom=$rsaBoom.SignData($bytesBoom,'SHA256')
  [IO.File]::WriteAllBytes($Signature,$signedBoom)
} finally { $rsaBoom.Dispose() }
