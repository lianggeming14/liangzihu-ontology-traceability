"""用原申报书第七节的规划参数生成商业说明和可复算工作簿。"""
from math import ceil
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[2] / "04_商业与调研"
OUT.mkdir(parents=True, exist_ok=True)
TITLE = "武昌鱼智慧养殖数据治理与溯源服务系统"
SUB = "基于“对象—来源—版本”一体可查的存量表格数据治理引擎"
FONT = Path("C:/Windows/Fonts")
INK, TEAL, PALE = "#183A42", "#116968", "#ECF4F2"
pdfmetrics.registerFont(TTFont("regular", str(FONT / "Deng.ttf")))
pdfmetrics.registerFont(TTFont("bold", str(FONT / "Dengb.ttf")))
pdf = canvas.Canvas(str(OUT / "商业策划书及访谈提纲.pdf"), pagesize=A4)
pdf.setTitle(TITLE + " 商业策划书及访谈提纲")
pdf.setAuthor("武昌鱼项目申报材料")
W,H=A4

def line(x,y,s,size=11,bold=False,color=INK):
    pdf.setFont("bold" if bold else "regular",size)
    pdf.setFillColor(HexColor(color)); pdf.drawString(x,y,s.replace("−", "-"))

def para(y,s,size=11,width=493,leading=18):
    buf=""
    for ch in s:
        if pdfmetrics.stringWidth(buf+ch,"regular",size)>width:
            line(50,y,buf,size); y-=leading; buf=""
        buf+=ch
    if buf: line(50,y,buf,size); y-=leading
    return y-7

def section(y,s):
    line(50,y,s,14,True,TEAL)
    return y-24

def page(num,tag,title,desc):
    line(50,H-53,TITLE,10,True,TEAL)
    line(50,H-70,SUB,9,False,TEAL)
    line(50,H-117,title,23,True)
    line(50,H-141,desc,10)
    pdf.setStrokeColor(HexColor("#BED2D0")); pdf.line(50,H-158,W-50,H-158)
    pdf.line(50,55,W-50,55)
    line(50,39,"B3 申报补充材料   /   "+tag,9,False,TEAL)
    line(W-80,39,f"{num} / 5",9)
    return H-192

def grid(y,headers,rows,widths):
    for i,row in enumerate([headers]+rows):
        pdf.setFillColor(HexColor(TEAL if i==0 else PALE if i%2 else "#F8FAFA"))
        pdf.rect(50,y-7,sum(widths),25,fill=1,stroke=0)
        x=50
        for val,wd in zip(row,widths):
            line(x+7,y+1,str(val),10,i==0,"#FFFFFF" if i==0 else INK); x+=wd
        y-=26
    return y-15

y=page(1,"商业策划书","商业策划书","实验室阶段   /   首轮试点方案   /   2026 年 11 月 24 日整理")
y=section(y,"服务对象与交付任务")
y=para(y,"首轮对象是已有电子台账、需要按批次交接、能指定人员解释数据的养殖合作社或企业。典型任务是从一个养殖批次回查塘口及来源行，查清暂不能确定的关联，并固定交接时双方读取的版本。")
y=para(y,"团队拟把服务边界定在客户已有资料的整理与复核。设备安装、替客户核定业务事实和跨单位数据授权另行约定。科教机构可将同一流程用于试验记录复查。")
y=section(y,"从评估到交付")
y=grid(y,["环节","拟交付给试点方的材料","核对人及完成条件"],[
["范围约定","任务、表单范围、授权与验收口径","业务负责人确认范围"],
["盘点与映射","字段字典、批次示例、来源映射","台账维护人抽查来源行"],
["导入与治理","导入结果、未解关系及异常清单","有权解释者核对存疑项"],
["版本交接","发布标识、导出文件、复核记录","接收方按同版本复查"],
["持续服务","数据字典维护、限定工时支持与备份复核","双方记录请求及处理工时"]],[83,203,207])
y=section(y,"收费及范围")
y=para(y,"试算采用一次实施费 8,000 元及年服务费 12,000 元。新增数据域、超范围对接和驻场所需工时单独评估。合同、许可与验收条件由双方确定。")
para(y,"本轮可核查成果来自工程与模拟台账。尚缺正式客户验收、成交与回款凭证，后页所列家数仅用于检验成本覆盖条件。")
pdf.showPage()
y=page(2,"商业策划书","试点推进与经营验证","拟在取得数据授权及业务人员配合后，选择至多两家开展有限试点。")
y=section(y,"用一次实际交接验证需求")
y=para(y,"第一月走访台账维护人、交接接收方和经费审批人。记录同一批次查找来源、确认归属、复查旧版本的现行步骤与耗时，确认谁能解释争议数据、谁能批准购买。")
y=para(y,"第二月在书面授权范围内选择可脱敏的文件。用固定任务和独立答案核查来源定位、未解记录识别及版本匹配。人工与系统的首次准备工时、逐题用时、正确数和误判数分别留存。")
y=para(y,"第三月与试点方逐项复核验收结果、报价接受条件、实施及支持工时。把未解决问题、额外服务范围、回款条件和维护责任写入试点复盘。")
y=section(y,"交付能力与退出条件")
y=para(y,"按基准假设，每新增一家首年使用 40 小时实施、24 小时支持、12 小时获客。8 家对应 608 小时，12 家对应 912 小时，均未计平台维护。排期前须核对可用人时和现场差旅。")
y=para(y,"缺少数据授权、无法约定独立答案或无人确认归属时，试点限于合成样例演示。若客户无法接受报价、交付工时持续超出约定，先缩小范围并重算单位贡献。")
y=section(y,"附录一　前置验证预算")
y=para(y,"原稿仅列约 56,500 元合计。以下为本轮规划拆分示例，便于试点时逐项询价。费用均待凭证核实，前置活动与日常维护分别记账。")
grid(y,["原型补强与测试","样本整理与字典","访谈与差旅","环境与部署验证","合计（元）"],[
["24,000","14,000","8,500","10,000","56,500"]],[112,110,84,110,77])
pdf.showPage()
y=page(3,"拟开展访谈","附录二　半结构化访谈提纲","使用空白记录表逐次填写。当前材料未包含已开展访谈的记录。")
y=section(y,"访谈对象与记录方式")
y=para(y,"分别约访记录维护人、接收核对人和预算审批人，每次约 30 分钟。开始前说明整理用途、资料范围与引用方式，请对方决定是否同意记录及署名。拒绝公开的内容仅用于获准范围。")
for head,body in [
("1　回顾最近一次交接","选一个已完成的批次，从交给谁、交了哪些表开始。遇到同名塘口、缺失值或多个版本时，谁判断采用哪份？一次具体差错如何发现并处理？"),
("2　现场走查一个任务","在授权且脱敏的样表上，请受访者找出指定批次的原始行，并说明判定依据。记下开始、结束、用到的文件、需要询问的人及仍无法回答的问题。"),
("3　检验系统能否解决问题","请受访者查看来源行、未解关系和历史版本，复述其含义。哪些信息仍需手工核对？请其定义可以签收的成果、可容忍的遗漏及不能接受的误判。"),
("4　辨认采购和维护条件","分别展示一次实施与年度服务的范围和价格；询问谁发起、审批、验收和支付。预算在哪个周期确定？新增表、人员更替和年度续约由谁负责？"),
("5　复核记录并约定后续","当场回读关键事实，标记对方原话、访谈者解释与待核对项。记录脱敏编号、角色、日期、授权范围、任务样本编号、核验方式和下次联系条件。")]:
    y=section(y,head); y=para(y,body)
pdf.showPage()
y=page(4,"财务模型","附录三　首年测算公式","单位为人民币元。这里衡量首年贡献覆盖成本的能力，未计税费、融资成本和回款时差。")
y=section(y,"单位经济")
for s in [
"每户收入 R = 实施费 + 年服务费 = 8,000 + 12,000 = 20,000。",
"直接成本 D = (40 + 24) 小时 × 100 元/小时 + 存储 1,200 + 交通 1,000 = 8,600。",
"获客成本 A = 12 小时 × 100 元/小时 + 交通 800 = 2,000。每户贡献 M = R − D − A = 9,400。",
"全年固定成本 F = 平台维护 30,000 + 管理协调 12,000 + 测试设施 6,000 + 合同文档 4,000 + 折旧摊销 8,000 = 60,000。前置投入 I 取 56,500。"]:
    y=para(y,s)
y=section(y,"三种客户数量情景")
y=grid(y,["首年客户","收入","直接及获客成本","扣固定后余额","再扣前置后余额"],[
["4 家","80,000","42,400","−22,400","−78,900"],["8 家","160,000","84,800","15,200","−41,300"],["12 家","240,000","127,200","52,800","−3,700"]],[70,80,117,109,117])
y=para(y,"令 N 为首年客户数。收入 = N × R，客户相关成本 = N × (D + A)，扣固定后余额 = N × M − F，扣前置后余额 = N × M − F − I。三行使用同一全年口径和同一单价。")
y=section(y,"成本覆盖门槛")
para(y,"贡献为正时，覆盖固定成本所需客户数为 F ÷ M 向上取整，即 7 家。加上前置验证投入后为 (F + I) ÷ M 向上取整，即 13 家。贡献小于或等于零时，增加同类客户无法覆盖正的固定成本。")
pdf.showPage()
y=page(5,"财务模型与引文","敏感性与证据来源","将报价和工时分别改变，观察成本覆盖门槛。")
y=grid(y,["假设","每户贡献","覆盖固定成本","加前置投入"],[
["基准","9,400 元","7 家","13 家"],["两项收费同时下调 20%","5,400 元","12 家","22 家"],["交付及获客工时增加 30%","7,120 元","9 家","17 家"]],[201,88,106,98])
y=para(y,"价格下调时直接与获客成本保持基准。工时增加时，76 小时对应人工成本从 7,600 元增至 9,880 元，交通、存储和固定成本保持基准。60,000 ÷ 7,120 向上取整为 9 家。原申报稿列为 10 家，按稿中明列的工时和费率复算后在附件与修订稿统一为 9 家。")
y=section(y,"模型取数")
y=para(y,"第七节 7.2 提供单位收费、人工、交通、存储、年固定成本及前置总额。三种情景按原稿 4、8、12 家重新计算。附录一的分项和拟访谈安排为本轮补制。当前没有 11 月 20 日原始财务底表可供逐格核对。")
y=section(y,"参考文献【11】核查记录")
y=para(y,"原稿给出的线索为设备采购和 255,167 元，缺少采购人、项目名称与编号。能核实的同金额行业案例来自广东惠州。修订稿将其作为异地服务采购案例单独引用，原设备公告身份仍待核实。")
y=para(y,"中国人民财产保险股份有限公司惠州市分公司．人保财险广东惠州分公司水产养殖防灾减损服务采购项目中选结果公告．发布平台为人保e采，日期为 2025-11-03，采购价格为 255,167 元，范围含监测预警、可视化和平台服务。公开页面未列公告编号。")
url="https://ec.picc.com/cms/default/webfile/4ywgg5/20251103/1170043791315304448.html"
line(50,y,"查看人保e采原公告",10,True,TEAL); pdf.linkURL(url,(50,y-3,160,y+12),relative=0)
line(50,y-19,url,9)
pdf.showPage(); pdf.save()

wb=Workbook(); s=wb.active; s.title="首年测算"
s.merge_cells("A1:E1"); s["A1"]="首年服务情景测算   /   规划假设"
s.merge_cells("A2:E2"); s["A2"]="蓝色为可修改假设。金额单位为元，测算包含完整首年服务。来源见商业策划书附录三。"
for r,row in enumerate([
["参数","取值","单位","口径"],["实施费",8000,"元/户","一次"],["年服务费",12000,"元/户","全年"],
["实施工时",40,"小时/户"],["支持工时",24,"小时/户"],["获客工时",12,"小时/户"],["工时单价",100,"元/小时"],
["存储摊销",1200,"元/户"],["实施交通",1000,"元/户"],["获客交通",800,"元/户"],["年固定成本",60000,"元","明细见附录三"],["前置投入",56500,"元","原稿约数"],["收费降幅",.2,"比例"],["工时增幅",.3,"比例"]],4):
    for j,v in enumerate(row,1): s.cell(r,j,v)
cached={}
def form(cell,formula,value):
    s[cell]=formula; cached[cell]=value
def rowat(r,vals):
    for c,v in enumerate(vals,1): s.cell(r,c,v)
rowat(19,["每户指标","基准","降价","加工时"])
for r,label in enumerate(["收入","直接交付成本","获客成本","单位贡献","覆盖固定所需户数","含前置所需户数"],20): s.cell(r,1,label)
for c,k,d in [("B",1,1),("C",.8,1),("D",1,1.3)]:
    mul="*(1-$B$16)" if c=="C" else ""
    inc="*(1+$B$17)" if c=="D" else ""
    rev=round(20000*k); direct=round(6400*d+2200); acq=round(1200*d+800); m=rev-direct-acq
    form(c+"20","=($B$5+$B$6)"+mul,rev)
    form(c+"21","=($B$7+$B$8)*$B$10"+inc+"+$B$11+$B$12",direct)
    form(c+"22","=$B$9*$B$10"+inc+"+$B$13",acq)
    form(c+"23",f"={c}20-{c}21-{c}22",m)
    form(c+"24",f'=IF({c}23>0,ROUNDUP($B$14/{c}23,0),"无法覆盖")',ceil(60000/m))
    form(c+"25",f'=IF({c}23>0,ROUNDUP(($B$14+$B$15)/{c}23,0),"无法覆盖")',ceil(116500/m))
rowat(27,["首年客户（家）","收入","直接及获客成本","扣固定后余额","再扣前置后余额"])
for r,n in enumerate([4,8,12],28):
    s.cell(r,1,n)
    form("B"+str(r),f"=A{r}*$B$20",n*20000)
    form("C"+str(r),f"=A{r}*($B$21+$B$22)",n*10600)
    form("D"+str(r),f"=B{r}-C{r}-$B$14",n*9400-60000)
    form("E"+str(r),f"=D{r}-$B$15",n*9400-116500)
for row in s:
    for a in row:
        hdr=a.row in (1,4,19,27)
        inputval=a.column==2 and 5<=a.row<=17 or a.column==1 and 28<=a.row<=30
        a.font=Font(name="Microsoft YaHei",size=14 if a.row==1 else 10,bold=hdr,color="FFFFFF" if hdr else "1A5D9D" if inputval else "183A42")
        if hdr: a.fill=PatternFill("solid",fgColor="116968")
        elif inputval: a.fill=PatternFill("solid",fgColor="EAF2F8")
        if a.data_type in ("n","f"): a.number_format='#,##0;[Red](#,##0);0'
        a.alignment=Alignment(vertical="center",horizontal="left" if a.data_type=="s" else "right")
for r in (16,17): s.cell(r,2).number_format="0%"
for col,width in enumerate([25,17,22,25,25],1): s.column_dimensions[get_column_letter(col)].width=width
for r in range(1,31): s.row_dimensions[r].height=20
s.sheet_view.showGridLines=False; s.freeze_panes="B5"; s.print_options.horizontalCentered=True
s.sheet_properties.pageSetUpPr.fitToPage=True; s.page_setup.fitToWidth=1; s.page_setup.fitToHeight=1
s.print_area="A1:E30"
mem=BytesIO(); wb.save(mem)
# Supply cached numerical results for previewers without a formula engine.
ns={"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
with ZipFile(mem) as src, ZipFile(OUT/"首年服务情景测算.xlsx","w") as dst:
    for info in src.infolist():
        data=src.read(info)
        if info.filename=="xl/worksheets/sheet1.xml":
            sheet=ET.fromstring(data)
            for node in sheet.findall(".//m:c",ns):
                if node.get("r") in cached: node.find("m:v",ns).text=str(cached[node.get("r")])
            data=ET.tostring(sheet,encoding="utf-8")
        dst.writestr(info,data)
