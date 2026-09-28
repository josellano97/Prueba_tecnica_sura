# Actualiza el índice del documento Word y lo exporta a PDF (requiere Microsoft Word instalado).
# Uso: powershell -ExecutionPolicy Bypass -File documento\exportar_pdf.ps1
$docx = Join-Path $PSScriptRoot "Respuestas_Prueba_Tecnica_Analista_Datos.docx"
$pdf = [IO.Path]::ChangeExtension($docx, ".pdf")
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {
    $d = $word.Documents.Open($docx)
    foreach ($t in $d.TablesOfContents) { $t.Update() }
    $d.Fields.Update() | Out-Null
    $d.Save()
    $d.ExportAsFixedFormat($pdf, 17)   # 17 = wdExportFormatPDF
    $d.Close()
    "PDF generado: $pdf"
} finally {
    $word.Quit()
}
