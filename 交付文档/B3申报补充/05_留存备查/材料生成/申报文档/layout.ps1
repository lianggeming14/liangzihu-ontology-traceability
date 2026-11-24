if($kind -eq 'form'){
    foreach($cs in @($d.SelectNodes('//w:trPr/w:cantSplit',$ns))){RemoveXml $cs}
    $table=$ps[2].SelectSingleNode('ancestor::w:tbl',$ns)
    $tr=@($table.SelectNodes('w:tr',$ns)); $after=$table.NextSibling
    $sets=@(@(3,4,5,6,7),@(8,9))
    foreach($indices in $sets){
        $newTable=$table.CloneNode($true)
        foreach($existing in @($newTable.SelectNodes('w:tr',$ns))){RemoveXml $existing}
        $br=E 'p';PProp $br 'pageBreakBefore' '1';$brP=$br.SelectSingleNode('w:pPr',$ns);$s=Ensure $brP 'spacing';SetA $s 'before' '0';SetA $s 'after' '0';SetA $s 'line' '20';SetA $s 'lineRule' 'exact'
        BodyInsert $br $after
        foreach($idx in $indices){$newTable.AppendChild($tr[$idx])|Out-Null}
        BodyInsert $newTable $after
    }
    foreach($tb in $d.SelectNodes('//w:body/w:tbl',$ns)){foreach($row in $tb.SelectNodes('w:tr',$ns)){foreach($pr in @($row.SelectNodes('.//w:keepNext|.//w:keepLines|.//w:pageBreakBefore',$ns))){RemoveXml $pr}}}
}
function FontP($p,$size,$bold){
    foreach($r in $p.SelectNodes('w:r',$ns)){
        if(!$r.SelectSingleNode('w:t',$ns)){continue}
        $rp=$r.SelectSingleNode('w:rPr',$ns);if(!$rp){$rp=E 'rPr';$r.PrependChild($rp)|Out-Null}
        $el=Ensure $rp 'sz';SetA $el 'val' "$size";$cs=Ensure $rp 'szCs';SetA $cs 'val' "$size"
        $bb=Ensure $rp 'b';if($bold){SetA $bb 'val' '1'}else{SetA $bb 'val' '0'}
        $cc=Ensure $rp 'color';SetA $cc 'val' '000000'
    }
}
function PSpace($p,$before,$after,$line){
    $pr=$p.SelectSingleNode('w:pPr',$ns);if(!$pr){$pr=E 'pPr';$p.PrependChild($pr)|Out-Null}
    $sp=Ensure $pr 'spacing';SetA $sp 'before' "$before";SetA $sp 'after' "$after";SetA $sp 'line' "$line";SetA $sp 'lineRule' 'exact'
    $snap=Ensure $pr 'snapToGrid';SetA $snap 'val' '0'
}
function Widths($table,$widths){
    $rows=@($table.SelectNodes('w:tr',$ns));$grid=$table.SelectSingleNode('w:tblGrid',$ns)
    foreach($c in @($grid.SelectNodes('w:gridCol',$ns))){RemoveXml $c}
    foreach($width in $widths){$c=E 'gridCol';SetA $c 'w' "$width";$grid.AppendChild($c)|Out-Null}
    $pr=$table.SelectSingleNode('w:tblPr',$ns);$tw=Ensure $pr 'tblW';SetA $tw 'w' (($widths|Measure-Object -Sum).Sum.ToString());SetA $tw 'type' 'dxa'
    foreach($row in $rows){$cells=@($row.SelectNodes('w:tc',$ns));if($cells.Count -ne $widths.Count){continue};for($j=0;$j -lt $cells.Count;$j++){
        $cp=$cells[$j].SelectSingleNode('w:tcPr',$ns);$cw=Ensure $cp 'tcW';SetA $cw 'w' ($widths[$j].ToString());SetA $cw 'type' 'dxa'
        foreach($gs in @($cp.SelectNodes('w:gridSpan|w:hMerge',$ns))){RemoveXml $gs}
    }}
}
if($kind -eq 'form'){
    $margin=$d.SelectSingleNode('//w:body/w:sectPr/w:pgMar',$ns);SetA $margin 'left' '1280';SetA $margin 'right' '1280';SetA $margin 'top' '1150';SetA $margin 'bottom' '1150'
    foreach($item in @($ps[27].SelectNodes('w:pPr/w:numPr|w:pPr/w:pStyle',$ns))){RemoveXml $item}
    foreach($tb in $d.SelectNodes('//w:body/w:tbl',$ns)){
        Widths $tb @(2100,7050)
        foreach($row in $tb.SelectNodes('w:tr',$ns)){
            $tc=@($row.SelectNodes('w:tc',$ns))
            for($j=0;$j -lt $tc.Count;$j++){
                $pr=$tc[$j].SelectSingleNode('w:tcPr',$ns); $borders=Ensure $pr 'tcBorders'
                foreach($dir in @('top','bottom','left','right')){$line=Ensure $borders $dir;SetA $line 'val' 'single';SetA $line 'sz' '5';SetA $line 'color' '999999'}
                $m=Ensure $pr 'tcMar';foreach($dir in @('top','bottom','left','right')){$x=Ensure $m $dir;SetA $x 'w' '80';SetA $x 'type' 'dxa'}
                foreach($p in $tc[$j].SelectNodes('w:p',$ns)){PSpace $p 0 60 340;FontP $p 23 ($j -eq 0)}
            }
        }
    }
    for($i=61;$i -le 74;$i++){PSpace $ps[$i] 0 90 305;FontP $ps[$i] 21 $false}
    PSpace $ps[60] 0 120 300;FontP $ps[60] 23 $true
    foreach($i in @(3,4,6)){FontP $ps[$i] 22 $true}
}
if($kind -eq 'report'){
    foreach($tb in $d.SelectNodes('//w:body/w:tbl',$ns)){
        $first=$tb.SelectSingleNode('w:tr/w:tc/w:p',$ns).InnerText
        if($first -eq '指标'){Widths $tb @(2240,5500,1250)}
        if($first -eq '项目'){Widths $tb @(1780,5130,2080)}
        if($first -eq '材料类别'){Widths $tb @(1550,5270,2170)}
        if($first -eq '客户类别'){Widths $tb @(2400,3290,3300)}
        if($first -eq '比较维度'){Widths $tb @(1230,1550,1430,1500,1430,1850)}
        $rows=@($tb.SelectNodes('w:tr',$ns))
        for($k=0;$k -lt $rows.Count;$k++){
            foreach($cell in $rows[$k].SelectNodes('w:tc',$ns)){
                $pr=$cell.SelectSingleNode('w:tcPr',$ns);$mar=Ensure $pr 'tcMar'
                foreach($dir in @('left','right','top','bottom')){$m=Ensure $mar $dir;SetA $m 'w' '55';SetA $m 'type' 'dxa'}
                if($k -eq 0){$sh=Ensure $pr 'shd';SetA $sh 'val' 'clear';SetA $sh 'fill' 'E6EBEF'}
                foreach($p in $cell.SelectNodes('w:p',$ns)){FontP $p 19 ($k -eq 0);PSpace $p 0 0 247}
            }
        }
    }
}


