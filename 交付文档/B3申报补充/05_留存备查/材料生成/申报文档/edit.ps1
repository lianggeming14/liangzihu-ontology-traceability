param([Parameter(Mandatory=$true)][string]$Project)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.Drawing
$base=Split-Path -Parent $MyInvocation.MyCommand.Path
$Project=(Resolve-Path -LiteralPath $Project).Path
$culture=[Globalization.CultureInfo]::InvariantCulture
$trialPath=Join-Path $Project '交付文档/B3申报补充/03_试验/试验汇总表.csv'
$trials=@(Import-Csv -LiteralPath $trialPath -Encoding UTF8)
$expected=@('66表正式SQL导入与全量回读','对象关系查询','发布','JSON分页完整导出')
$display=@('66表正式 SQL 导入与回读','查询含关联的塘口详情','发布并登记','JSON 完整分页导出')
$trialTable=@(,@('操作与计时边界','三次用时（秒）','均值（秒）'))
for($j=0;$j -lt $expected.Count;$j++){
  $result=@($trials | Where-Object { $_.操作 -eq $expected[$j] })
  if($result.Count -ne 1){throw "计时汇总表中找不到唯一结果：$($expected[$j])"}
  $times=@(foreach($name in @('第1次_秒','第2次_秒','第3次_秒')){[double]::Parse($result[0].$name,$culture)})
  $mean=[double]::Parse($result[0].三次算术均值_秒,$culture)
  if([math]::Abs(($times|Measure-Object -Average).Average-$mean) -gt 0.00001){throw "计时均值不相符：$($expected[$j])"}
  $triplet=($times|ForEach-Object {$_.ToString('0.000',$culture)}) -join ' / '
  $rounded=$mean.ToString('0.000',$culture);if($j -eq 0){$fullMean=$rounded}
  $trialTable+=,@($display[$j],$triplet,$rounded)
}
$values=(Get-Content -Encoding utf8 -Raw (Join-Path $base 'edits.json')).Replace('［整批均值］',$fullMean) | ConvertFrom-Json
$extra=Get-Content -Encoding utf8 -Raw (Join-Path $base 'results.json') | ConvertFrom-Json
$out=Join-Path $Project '交付文档/B3申报补充/01_申报材料'
$images=Join-Path $out '原有插图'
New-Item -ItemType Directory -Force $images | Out-Null
$w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
$rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
$ds='http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
$gfx='http://schemas.openxmlformats.org/drawingml/2006/main'
function Part([string]$path){
    $entry=$z.GetEntry($path); $stream=$entry.Open()
    try {$doc=New-Object Xml.XmlDocument; $doc.PreserveWhitespace=$true; $doc.Load($stream); return ,$doc} finally {$stream.Dispose()}
}
function SavePart([string]$name,[System.Xml.XmlDocument]$tree){
    $old=$z.GetEntry($name); if($old){$old.Delete()}
    $n=$z.CreateEntry($name); $st=$n.Open()
    try {$writer=[Xml.XmlWriter]::Create($st,([Xml.XmlWriterSettings]@{Encoding=[Text.UTF8Encoding]::new($false);Indent=$false}));$tree.Save($writer);$writer.Dispose()} finally {$st.Dispose()}
}
function E([string]$name){return ,$d.CreateElement('w',$name,$w)}
function SetA($element,[string]$key,[string]$val){$element.SetAttribute($key,$w,$val) | Out-Null}
function Ensure($element,[string]$key){$child=$element.SelectSingleNode("w:$key",$ns);if(!$child){$child=E $key;$element.AppendChild($child) | Out-Null}; return ,$child}
function RemoveXml($el){if($el -and $el.ParentNode){$el.ParentNode.RemoveChild($el) | Out-Null}}
function TextP($p,[string]$v){
    $pr=$p.SelectSingleNode('w:r/w:rPr',$ns)
    if($pr){$pr=$pr.CloneNode($true)}
    foreach($node in @($p.ChildNodes)){if($node.LocalName -ne 'pPr'){RemoveXml $node}}
    $r=E 'r';if($pr){$r.AppendChild($pr) | Out-Null}
    $tt=E 't';$tt.InnerText=$v;$r.AppendChild($tt) | Out-Null;$p.AppendChild($r) | Out-Null
}
function CleanR($scope){
    foreach($el in @($scope.SelectNodes('.//w:highlight|.//w:commentRangeStart|.//w:commentRangeEnd|.//w:commentReference',$ns))){RemoveXml $el}
    foreach($el in @($scope.SelectNodes('.//w:color',$ns))){if($el.GetAttribute('val',$w) -in @('C00000','FF0000','595959')){SetA $el 'val' '000000'}}
}
function Paragraph([string]$v,$model,$before){
    $q=$model.CloneNode($true);TextP $q $v;$before.ParentNode.InsertBefore($q,$before)|Out-Null;return ,$q
}
function PProp($p,[string]$flag,[string]$val='1'){
    $pr=$p.SelectSingleNode('w:pPr',$ns);if(!$pr){$pr=E 'pPr'; $p.PrependChild($pr)|Out-Null}
    $x=Ensure $pr $flag;SetA $x 'val' $val
}
function ShapeSize($shape,[double]$ratio){
    foreach($el in @($shape.SelectNodes('.//wp:extent|.//a:xfrm/a:ext',$ns))){
       foreach($dim in @('cx','cy')){$el.SetAttribute($dim,([math]::Round([double]$el.GetAttribute($dim)*$ratio)).ToString())}
    }
}
function BodyInsert($child,$before){$before.ParentNode.InsertBefore($child,$before)|Out-Null}
function ApplyMap($mapping){if($mapping){foreach($it in $mapping.PSObject.Properties){TextP $ps[[int]$it.Name] $it.Value}}}
foreach($kind in @('report','form')){
  if($kind -eq 'report'){$source='武昌鱼项目_B3申报书.docx';$dest='武昌鱼项目_B3申报书_研究报告.docx'}
  else {$source='B3申报作品情况_v1.docx';$dest='B3申报作品情况_报送核对版.docx'}
  $sourceHash=(Get-FileHash -LiteralPath (Join-Path $Project $source) -Algorithm SHA256).Hash
  $expectedHash=@{report='9054E7C7F9BC9F0EA136C2B2DFBB46EEC9E9B3D697A1CF11F60EF0E0CC0FDFAF';form='FA88C92703D71BC6BE197EEF3523DC4A480FB85E8280256F45206217FBD5CE12'}
  if($sourceHash -ne $expectedHash[$kind]){throw "原表已变更，须重新定位正文及表格段落：$source"}
  $dest=Join-Path $out $dest
  $staged=Join-Path $out ('.申报编制-'+[guid]::NewGuid().ToString('N')+'.tmp')
  try {
  Copy-Item -LiteralPath (Join-Path $Project $source) -Destination $staged
  $z=[IO.Compression.ZipFile]::Open($staged,[IO.Compression.ZipArchiveMode]::Update)
  try{
    $d=Part 'word/document.xml';$ns=[Xml.XmlNamespaceManager]::new($d.NameTable)
    $ns.AddNamespace('w',$w);$ns.AddNamespace('wp',$ds);$ns.AddNamespace('a',$gfx);$ns.AddNamespace('r',$rel)
    $ps=@($d.SelectNodes('//w:body//w:p',$ns))
    ApplyMap $values.$kind
    if($kind -eq 'report'){
      $picnames=@('图1_系统架构','图2_数据流程','图3a_治理工作台','图3b1_塘口与批次关联','图3b2_水质记录与来源定位','图3b3_地图候选田块查询')
      for($i=1;$i -le 6;$i++){
        $entry=$z.GetEntry(('word/media/image{0}.png' -f $i))
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,(Join-Path $images ($picnames[$i-1]+'.png')),$true)
      }
      $ct=Part '[Content_Types].xml';$rels=Part 'word/_rels/document.xml.rels'
      foreach($node in @($rels.DocumentElement.ChildNodes)){if($node.Target -match 'comments|people'){RemoveXml $node}}
      foreach($node in @($ct.DocumentElement.ChildNodes)){if($node.PartName -match 'comments|people'){RemoveXml $node}}
      foreach($e in @($z.Entries)){if($e.FullName -match '^word/(comments|people)'){$e.Delete()}}
      $metrics=$ps[25].SelectSingleNode('ancestor::w:tbl',$ns)
      $cmp=$ps[64].SelectSingleNode('ancestor::w:tbl',$ns)
      $ph=$ps[114].SelectSingleNode('ancestor::w:tbl',$ns);RemoveXml $ph
      RemoveXml $ps[167].SelectSingleNode('ancestor::w:tr',$ns)
      $oldImageP=$ps[11]
      $sect=$d.SelectSingleNode('//w:body/w:sectPr',$ns)
      $page=$sect.SelectSingleNode('w:pgSz',$ns)
      SetA $page 'w' '11906';SetA $page 'h' '16838'
      $margin=$sect.SelectSingleNode('w:pgMar',$ns);SetA $margin 'left' '1250';SetA $margin 'right' '1250'
      foreach($i in @(11,14,117,118,119,120)){PProp $ps[$i] 'jc' 'center'}
      foreach($i in @(4,5,7,9,12,15,19,24,60,61,63,122,136,139,140,142,172,174,195)){PProp $ps[$i] 'keepNext'}
      foreach($i in @(58,116,121,135,170,193)){if($ps[$i].ParentNode.LocalName -eq 'body'){RemoveXml $ps[$i]}}
      $b=$ps[60]
      $null=Paragraph '4.1 冻结版本复测' $ps[5] $b
      $null=Paragraph $extra.frozen $ps[6] $b
      $null=Paragraph '4.2 三次计时与试验曲线' $ps[5] $b
      $null=Paragraph $extra.env $ps[6] $b
      $tab=$metrics.CloneNode($true)
      $rows=@($tab.SelectNodes('w:tr',$ns));$valuesTable=$trialTable
      for($i=0;$i -lt $rows.Count;$i++){if($i -ge $valuesTable.Count){RemoveXml $rows[$i];continue};$cells=@($rows[$i].SelectNodes('w:tc',$ns));for($j=0;$j -lt 3;$j++){TextP $cells[$j].SelectSingleNode('w:p',$ns) $valuesTable[$i][$j]}}
      $colWidths=@(3200,3300,2200);$cols=@($tab.SelectNodes('w:tblGrid/w:gridCol',$ns));for($i=0;$i -lt 3;$i++){SetA $cols[$i] 'w' ($colWidths[$i].ToString())}
      foreach($row in $tab.SelectNodes('w:tr',$ns)){$cs=@($row.SelectNodes('w:tc',$ns));for($i=0;$i -lt 3;$i++){SetA $cs[$i].SelectSingleNode('w:tcPr/w:tcW',$ns) 'w' ($colWidths[$i].ToString())}}
      BodyInsert $tab $b
      $null=Paragraph $extra.boundary $ps[6] $b
      if($extra.graph){
        $f=Get-Item -LiteralPath (Join-Path $Project $extra.graph)
        $e=$z.CreateEntry('word/media/b3-comparison.png');$stm=$e.Open();$fstm=$f.OpenRead();$fstm.CopyTo($stm);$fstm.Dispose();$stm.Dispose()
        $link=$rels.CreateElement('Relationship',$rels.DocumentElement.NamespaceURI);$link.SetAttribute('Type',$rel+'/image');$link.SetAttribute('Id','rIdB3Curve01');$link.SetAttribute('Target','media/b3-comparison.png');$rels.DocumentElement.AppendChild($link) | Out-Null
        $np=$oldImageP.CloneNode($true);$blip=$np.SelectSingleNode('.//a:blip',$ns);$blip.SetAttribute('embed',$rel,'rIdB3Curve01')|Out-Null
        $np.SelectSingleNode('.//wp:docPr',$ns).SetAttribute('id','101');$np.SelectSingleNode('.//wp:docPr',$ns).SetAttribute('descr','四项操作三次独立计时，精确值见表。')
        $img=[Drawing.Image]::FromFile($f.FullName);$cx=5300000;$cy=[int]($cx*$img.Height/$img.Width);$img.Dispose()
        foreach($x in @($np.SelectNodes('.//wp:extent|.//a:xfrm/a:ext',$ns))){$x.SetAttribute('cx',"$cx");$x.SetAttribute('cy',"$cy")}
        PProp $np 'keepNext';BodyInsert $np $b
        $cap=Paragraph $extra.caption $ps[2] $b;PProp $cap 'jc' 'center'
      }
      if($extra.intake){
        $null=Paragraph '4.3 完整批次的接收与发布条件' $ps[5] $b
        foreach($finding in $extra.intake){$null=Paragraph $finding $ps[6] $b}
      }
      $srcCaption=Paragraph '图1　系统架构与证据链' $ps[2] $ps[12];PProp $srcCaption 'jc' 'center';PProp $ps[11] 'keepNext'
      $srcCaption=Paragraph '图2　从接收、校验到发布和交接的流程' $ps[2] $ps[15];PProp $srcCaption 'jc' 'center';PProp $ps[14] 'keepNext'
      $stub=Paragraph '图3　治理工作台、关系查询与来源定位的界面' $ps[5] $ps[117];PProp $stub 'keepNext';
      foreach($i in @(117,118,119,120)){ShapeSize $ps[$i] 0.99}
      foreach($tb in @($d.SelectNodes('//w:body/w:tbl',$ns))){
        $first=$tb.SelectSingleNode('w:tr',$ns);$rp=Ensure $first 'trPr';$null=Ensure $rp 'tblHeader'
        foreach($row in $tb.SelectNodes('w:tr',$ns)){$pr=Ensure $row 'trPr';$null=Ensure $pr 'cantSplit'}
      }
      SavePart 'word/_rels/document.xml.rels' $rels;SavePart '[Content_Types].xml' $ct
    }else{
      foreach($i in @(54,55,56,57,58,59)){RemoveXml $ps[$i]}
      foreach($h in @($d.SelectNodes('//w:trPr/w:trHeight',$ns))){RemoveXml $h}
      foreach($row in $d.SelectNodes('//w:body/w:tbl/w:tr',$ns)){$rp=Ensure $row 'trPr';$null=Ensure $rp 'cantSplit'}
    }
    CleanR $d.DocumentElement
    if(Test-Path (Join-Path $base 'layout.ps1')){ . (Join-Path $base 'layout.ps1') }
    $core=Part 'docProps/core.xml'
    foreach($item in @($core.DocumentElement.ChildNodes)){
      if($item.LocalName -in @('creator','lastModifiedBy','description','title')){RemoveXml $item}
      elseif($item.LocalName -eq 'modified'){$item.InnerText=[DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')}
    }
    $title=$core.CreateElement('dc','title','http://purl.org/dc/elements/1.1/');$title.InnerText=$ps[1].InnerText
    if($kind -eq 'form'){$title.InnerText=$ps[3].InnerText+$ps[4].InnerText}
    $core.DocumentElement.AppendChild($title)|Out-Null;SavePart 'docProps/core.xml' $core
    if($z.GetEntry('docProps/custom.xml')){
      $propsRels=Part '_rels/.rels';$ct=Part '[Content_Types].xml'
      foreach($item in @($propsRels.DocumentElement.ChildNodes)){if($item.Target -eq 'docProps/custom.xml'){RemoveXml $item}}
      foreach($item in @($ct.DocumentElement.ChildNodes)){if($item.PartName -eq '/docProps/custom.xml'){RemoveXml $item}}
      $z.GetEntry('docProps/custom.xml').Delete();SavePart '_rels/.rels' $propsRels;SavePart '[Content_Types].xml' $ct
    }
    SavePart 'word/document.xml' $d
  }finally{$z.Dispose()}
  if(Test-Path -LiteralPath $dest){[IO.File]::Replace($staged,$dest,[Management.Automation.Language.NullString]::Value)}else{[IO.File]::Move($staged,$dest)}
  } finally { if(Test-Path -LiteralPath $staged){Remove-Item -LiteralPath $staged} }
  Get-Item $dest | Select-Object Name,Length
}

