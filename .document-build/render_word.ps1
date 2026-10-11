param([string]$InputFile,[string]$PdfFile)
$ErrorActionPreference='Stop'
$wordApp=$null
$wordDoc=$null
try {
  $wordApp=New-Object -ComObject Word.Application
  $wordApp.Visible=$false
  $wordApp.DisplayAlerts=0
  $wordApp.AutomationSecurity=3
  $wordDoc=$wordApp.Documents.Open($InputFile,$false,$false,$false)
  foreach($toc in $wordDoc.TablesOfContents){$toc.Update()}
  $wordDoc.Fields.Update() | Out-Null
  $wordDoc.Repaginate()
  foreach($toc in $wordDoc.TablesOfContents){$toc.UpdatePageNumbers()}
  $wordDoc.Save()
  $wordDoc.ExportAsFixedFormat($PdfFile,17)
  Write-Output ('PAGES='+$wordDoc.ComputeStatistics(2))
  Write-Output ('PDF='+$PdfFile)
} finally {
  if($null -ne $wordDoc){$wordDoc.Close(0);[System.Runtime.InteropServices.Marshal]::ReleaseComObject($wordDoc) | Out-Null}
  if($null -ne $wordApp){$wordApp.Quit();[System.Runtime.InteropServices.Marshal]::ReleaseComObject($wordApp) | Out-Null}
}
