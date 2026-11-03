const labels={paper_perimeter:'纸面周长',paper_area:'纸面面积',paper_length:'纸面线长',estimated_perimeter:'参考长度推算周长',estimated_area:'参考长度推算面积',estimated_length:'参考长度推算线长',scenario_perimeter:'比例尺情景周长',scenario_area:'比例尺情景面积',scenario_length:'比例尺情景线长',channel_depth:'沟渠深度',bottom_elevation:'渠底高程',project_mean_dredging_thickness:'工程平均清淤厚度',labelled_length:'图注长度',work_area:'工程面积',earthwork_volume:'工程方量',linear_work_quantity:'工程延米量',width:'宽度',item_count:'数量',ledger_area_unit_unconfirmed:'台账面积（单位待核）',unresolved_field_annotation_number:'田块框内数值（含义待核）'};
export function measurementLabel(m){return labels[m.kind]||m.kind;}
export function measurementValue(m){const value=Array.isArray(m.value_original)?m.value_original.join(' × '):String(m.value_original??'未标注');return value+(m.unit?' '+m.unit:'（单位未明确）');}
export function profileSummary(p){
 const lines=[],paper=p.paper_metrics,ground=p.ground_estimate;
 if(paper.perimeter_pt!=null)lines.push(`纸面周长：${paper.perimeter_pt.toFixed(2)} pt`);
 if(paper.area_pt2!=null)lines.push(`纸面面积：${paper.area_pt2.toFixed(2)} pt²`);
 if(ground.perimeter_m!=null)lines.push(`参考长度推算周长：${ground.perimeter_m} m（${ground.perimeter_range_m.join('–')} m）`);
 if(ground.area_m2!=null)lines.push(`参考长度推算面积：${ground.area_m2} m²`);
 if(ground.perimeter_m!=null||ground.area_m2!=null)lines.push('上述范围来自参考线比例差异，未包含全部描线误差，尚非实测。');
 for(const s of p.scale_scenarios||[])if(s.perimeter_m!=null)lines.push(`仅在 1:${s.scale_denominator} 成立时：周长 ${s.perimeter_m} m，面积 ${s.area_m2} m²`);
 if(p.kind==='pond')lines.push('本塘水深：原图未提供可可靠关联的逐塘水深。沟深、渠底高程、清淤厚度分别查询。');
 lines.push(`关联属性记录：${p.measurement_ids.length} 条`);
 return lines.join('\n');
}
