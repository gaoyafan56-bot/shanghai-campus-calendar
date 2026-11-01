#!/usr/bin/env python3
"""上海13校公开招聘日历。无需账号、密码或自建服务器。

原始数据源及详情规则见 SOURCES；不包含复旦、上海海事、上海师大。
已知规则：上大/上理/上外贸不调用登录详情接口，详情回退列表；
上财列表必须带 nrdm=allxjh1，优先 POST /career/index/common/jyrl date=YYYY-MM；
上交/华师/上财列表卡片缺日期，使用官网月历 JSON；若 JSON 无日期，不用发布日期冒充；
上外 preaching.html?wid=；东华现为 page/preaching.html?wid=，华理 RecruitmentDetail.aspx?id=；
同济历史规则 newsDetail.html?id=，现优先使用接口返回的官方详情 URL；
上电 teachin/view/id/；华政回退日程列表；海洋 SPA 无逐场页，回退官网首页。
所有请求只访问公开页面。遇到登录/验证码/无法解析时跳过、保留旧记录并报告。
抓取窗口：上个月到未来两个月；已采集历史永久保留，不承诺补齐官网全部历史。
"""
import argparse, base64, calendar, concurrent.futures, datetime as dt
import json, logging, os, re, time, urllib.parse, urllib.request, zlib
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo('Asia/Shanghai')
SOURCES = {
 '上海大学': 'https://job.shu.edu.cn/home/recruit-info/xjh-list',
 '上海交通大学': 'https://www.job.sjtu.edu.cn/career/xjhxx?nrdm=zcxjh1',
 '同济大学': 'https://tj91.tongji.edu.cn/frontpage/tongji/html/recruitmentFairList.html',
 '华东师范大学': 'https://career.ecnu.edu.cn/career/xjhxx',
 '华东理工大学': 'https://career.ecust.edu.cn/InformationNAVList.aspx?RA=1',
 '东华大学': 'https://ejob.dhu.edu.cn/category/zpxx-parent/xjhxx.html',
 '上海财经大学': 'https://career.sufe.edu.cn/career/xjhxx?nrdm=allxjh1',
 '上海外国语大学': 'https://career.shisu.edu.cn/category/zpzq/zprl.html',
 '上海理工大学': 'https://91.usst.edu.cn/home/recruit-info/xjh-list',
 '上海海洋大学': 'https://jcxt.shou.edu.cn/',
 '华东政法大学': 'https://jy.ecupl.edu.cn/16901/list.htm',
 '上海对外经贸大学': 'https://job.suibe.edu.cn/home/recruit-info/xjh-list',
 '上海电力大学': 'https://career.shiep.edu.cn/teachin',
}
SPA = {'上海大学', '上海理工大学', '上海海洋大学', '上海对外经贸大学'}
CAREER = {'上海交通大学', '华东师范大学', '上海财经大学'}
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36', 'Accept-Language': 'zh-CN,zh;q=0.9', 'Accept': '*/*'}

END_DATES = {}

def request(url, form=None):
    """超时与退避重试；不关闭 TLS 校验，不携带任何登录凭证。"""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=None if form is None else
                urllib.parse.urlencode(form).encode(), headers={**HEADERS, 'Referer': url})
            with urllib.request.urlopen(req, timeout=20) as response:
                return response.read().decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def json_request(url, form=None):
    value = request(url, form).strip()
    # 安全解析官网 JSONP，不执行 JavaScript/eval。
    if not value.startswith(('{', '[')):
        match = re.fullmatch(r'[\w.$]+\((.*)\);?', value, re.S)
        if not match:
            raise ValueError('返回内容不是 JSON/JSONP，可能是登录页或验证码')
        value = match[1]
    return json.loads(value)


def date(value):
    match = re.search(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})', re.sub(r'\s+', '', str(value or '')))
    return dt.date(*map(int, match.groups())).isoformat() if match else ''


def times(value):
    return [f'{int(h):02d}:{int(m):02d}' for h, m in
            re.findall(r'(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)', str(value or ''))]


def event(school, day, start, end, title, venue, link, kind=''):
    day = date(day)
    starts, ends = times(start), times(end)
    if not day or not starts or not str(title or '').strip():
        raise ValueError('记录缺少明确的活动日期/开始时间/名称')
    title = BeautifulSoup(str(title), 'html.parser').get_text(' ', strip=True)
    kind = {'XJH':'宣讲会','ZPH':'招聘会','xjh':'宣讲会','zph':'招聘会'}.get(kind,kind)
    if '双选' in title:
        kind = '双选会'
    elif '招聘会' in title:
        kind = '招聘会'
    kind = kind if kind in ('宣讲会', '双选会', '招聘会') else '宣讲会'
    venue = str(venue or '').strip()
    if re.search('线上|空中|在线|腾讯会议|直播', venue + title):
        venue = '线上'
    link = urllib.parse.urljoin(SOURCES[school], str(link or SOURCES[school]))
    # 只允许学校官网域名及其子域名；异常第三方跳转回退官方列表。
    host = urllib.parse.urlparse(link).hostname or ''
    school_domain = '.'.join(urllib.parse.urlparse(SOURCES[school]).hostname.split('.')[-3:])
    if not (host == school_domain or host.endswith('.' + school_domain)):
        link = SOURCES[school]
    finish = ends[0] if ends else (starts[1] if len(starts)>1 else '')
    # 只有官网明确给出次日日期时，才保留早于开始时间的结束时刻。
    if finish and finish <= starts[0] and not (date(end) and date(end) > day):
        logging.warning('%s %s：官网结束时刻未晚于开始时刻，end留空待核验',school,title)
        finish = ''
    if finish and date(end) and date(end)>day:
        END_DATES[school+'|'+link+'|'+day] = date(end)
    return dict(d=day, start=starts[0], end=finish,
                co=title, venue=venue or '官网未公布', school=school, type=kind, link=link)


def months(today):
    n = today.year * 12 + today.month - 1
    return [f'{(n+i)//12:04d}-{(n+i)%12+1:02d}' for i in (-1, 0, 1, 2)]


def career(school, today):
    """已实测三校都提供公开 jyrl，含宣讲、双选/招聘会及完整日期。"""
    base = SOURCES[school].split('/career/')[0] + '/career/'
    result = []
    for month in months(today):
        body = json_request(base + 'index/common/jyrl', {'date': month})
        if body.get('code') != 200 or not isinstance(body.get('data'), list):
            raise ValueError('官网月历接口失效或需要登录')
        for group in body['data']:
            for row in group.get('con', []):
                if row.get('type') not in ('xjh', 'zph'):
                    continue
                venue = '线上' if row.get('jbxs') == '02' else row.get('cdmc')
                result.append(event(school, row.get('mark') or group.get('mark'), row.get('jbsj'),
                    row.get('event_end'), row.get('xjhzt') or row.get('con'), venue,
                    urllib.parse.urljoin(base, row.get('a', '')), '招聘会' if row['type']=='zph' else '宣讲会'))
    return result


def spa(school, today):
    """新公开接口；加密响应由学校网页自身解析，不硬编码任何密钥。"""
    base = urllib.parse.urlsplit(SOURCES[school])
    origin = f'{base.scheme}://{base.netloc}'
    mm = months(today)
    final_month = dt.date.fromisoformat(mm[-1] + '-01')
    end = final_month.replace(day=calendar.monthrange(final_month.year, final_month.month)[1])
    rows = []
    encrypted = False
    # t=0 是招聘会，t=1 是宣讲会；不能只抓一种。
    for kind in (0, 1):
        params = urllib.parse.urlencode(dict(s=mm[0]+'-01', e=end.isoformat(), t=kind))
        body = json_request(origin + '/api/CareerFairs/GetActivityList?' + params)
        if body.get('code') != 0:
            raise ValueError('公开列表接口拒绝访问或需要登录')
        if body.get('encrypted'):
            encrypted = True
            break
        if not isinstance(body.get('data'), dict) or not isinstance(body['data'].get('vo'), list):
            raise ValueError('公开列表字段发生变化')
        rows.extend(body['data']['vo'])
    if encrypted:
        rows = rendered_spa(school, mm)
    return [event(school, r.get('hdrq'), r.get('hdkssj'), r.get('hdjssj'),
                  r.get('hdmc'), r.get('hddd'), SOURCES[school], r.get('hdlx'))
            for r in rows if r.get('hdlx') in ('宣讲会', '招聘会', '双选会', 'XJH', 'ZPH')]


def rendered_spa(school, mm):
    """加载学校自身公开 JS 模块解析其响应，不复制或硬编码密钥。
    全新临时浏览器无登录信息；只调用官网日历所用的公开列表接口。
    """
    from playwright.sync_api import sync_playwright
    result = []
    origin = 'https://' + urllib.parse.urlparse(SOURCES[school]).netloc
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale='zh-CN', timezone_id='Asia/Shanghai')
        try:
            page.goto(SOURCES[school], wait_until='domcontentloaded', timeout=60000)
            script = page.locator('script[type="module"][src]').first.get_attribute('src')
            if not script:
                raise ValueError('官网公开应用模块入口发生变化')
            last = dt.date.fromisoformat(mm[-1]+'-01')
            end = last.replace(day=calendar.monthrange(last.year,last.month)[1]).isoformat()
            for kind in (0, 1):
                params = urllib.parse.urlencode(dict(s=mm[0]+'-01', e=end, t=kind))
                body = page.evaluate("""async ({script, path}) => {
                    const module = await import(script);
                    const helper = Object.values(module).find(value =>
                        value && typeof value.httpGetInvoke === 'function');
                    if (!helper) throw new Error('官网公开请求辅助模块已变化');
                    return await helper.httpGetInvoke(path);
                }""", dict(script=urllib.parse.urljoin(origin,script),
                            path='/CareerFairs/GetActivityList?'+params))
                if body.get('code') != 0 or not isinstance(body.get('data'),dict):
                    raise ValueError('官网公开日历未返回有效数据')
                rows = body['data'].get('vo')
                if not isinstance(rows,list):
                    raise ValueError('官网公开日历字段发生变化')
                result.extend(rows)
        finally:
            browser.close()
    logging.info('%s 公开日历原始场次：%d',school,len(result))
    return result


def jsonp_school(school):
    base = 'https://' + urllib.parse.urlparse(SOURCES[school]).netloc
    rows = []
    # 分别抓宣讲和招聘会，完整翻页，不依赖“当前/未结束”默认筛选。
    for resource, kind in [('preaching', '宣讲会'), ('recruitment', '招聘会')]:
        page = 1
        while True:
            params = urllib.parse.urlencode(dict(type='list', eachPageRows=100, currentPageno=page, callback='calendarCallback'))
            body = json_request(base + '/pros_jiuye/s/zxh/owebsiteData/' + resource + '?' + params)
            if not isinstance(body.get('listData'), list):
                raise ValueError(f'{resource} 返回字段变化')
            for r in body['listData']:
                rows.append(event(school, r.get('apkssj'), r.get('apkssj'), r.get('apjssj'),
                    r.get('zt') or r.get('zph') or r.get('yrdwname'), r.get('jbdd') or r.get('cdzdy'),
                    base + ('/page/' if school=='东华大学' else '/') + ('preaching.html?wid=' if kind=='宣讲会' else 'recruitment.html?wid=') + str(r['wid']), kind))
            if page >= int(body.get('totalPages') or 0):
                break
            page += 1
            if page > 100:
                raise ValueError('超过100页上限，需检查接口分页')
    return rows


def tongji():
    result, page = [], 1
    while True:
        body = json_request('https://tj91.tongji.edu.cn/f/recruitmentFair/ajax_frontRecruitfair', {'pageNo':page,'pageSize':100})
        if body.get('state') != 1 or not isinstance(body.get('object'), dict):
            raise ValueError('同济接口失效')
        data = body['object']
        for r in data['list']:
            kind = '招聘会' if str(r.get('fairType')) in ('3','4','5','6') else '宣讲会'
            result.append(event('同济大学', r.get('startTime'), r.get('startTime'), r.get('endTime'),
                r.get('title'), r.get('place'), r.get('url') or SOURCES['同济大学'], kind))
        if page >= int(data.get('totalPage') or 0):
            break
        page += 1
        if page > 100:
            raise ValueError('同济分页超限')
    return result


def ecust():
    result, current = [], 1
    url = SOURCES['华东理工大学']
    html = request(url)
    cutoff = months(dt.datetime.now(TZ).date())[0] + '-01'
    while True:
        soup = BeautifulSoup(html, 'html.parser')
        page_events = []
        for a in soup.select('a[href*="RecruitmentDetail.aspx?id="]'):
            text = a.get_text(' ', strip=True)
            if '召开时间' not in text:
                continue
            when = re.search(r'召开时间[：:]\s*(.*?)(?=召开地点)', text)
            place = re.search(r'召开地点[：:]\s*(.*)', text)
            if not when:
                raise ValueError('华理活动时间字段已变化')
            page_events.append(event('华东理工大学', when[1], when[1], '', text.split('召开时间')[0],
                                      place[1] if place else '', a['href']))
        if not page_events:
            raise ValueError('华理未解析到活动卡片')
        result.extend(page_events)
        if max(e['d'] for e in page_events) < cutoff:
            break
        buttons = [a for a in soup.select('a[href*="__doPostBack"]')
                   if a.get_text(strip=True).isdigit() and int(a.get_text(strip=True)) > current]
        if not buttons:
            break
        button = min(buttons, key=lambda a:int(a.get_text(strip=True)))
        current = int(button.get_text(strip=True))
        if current > 100:
            raise ValueError('华理分页超过100页，请检查')
        target = re.search(r"__doPostBack\('([^']*)','([^']*)'\)", button['href'])
        if not target:
            raise ValueError('华理翻页机制已变化')
        form = {i['name']:i.get('value','') for i in soup.select('input[type=hidden][name]')}
        form.update(__EVENTTARGET=target[1], __EVENTARGUMENT=target[2])
        html = request(url, form)
    try:
        result.extend(ecust_notices())
    except Exception as exc:
        logging.warning('华理招聘会公告补充来源失败：%s；已取得的宣讲会仍保留',exc)
    return result


def ecust_notices():
    """补充公告栏中的招聘/双选会；只有明确举办日期和时刻才入日历。"""
    origin='https://career.ecust.edu.cn'
    url=origin+'/InformationNAVList.aspx?'+urllib.parse.urlencode({'type':'公告公示','subinfotypedm':'18'})
    soup=BeautifulSoup(request(url),'html.parser')
    links={urllib.parse.urljoin(origin,a['href']):a.get_text(' ',strip=True) for a in soup.select('a[href*="InformationDetail.aspx?XXID="]') if re.search('招聘会|双选会',a.get_text())}
    result=[]
    for link,title in links.items():
        detail=BeautifulSoup(request(link),'html.parser')
        content=detail.select_one('.inf0_list')
        if not content:
            continue
        text=re.sub(r'\s+','',content.get_text(' ',strip=True))
        match=re.search(r'(?:大会时间|会议时间|举办时间|活动时间)[：:]?((?:20\d{2})年\d{1,2}月\d{1,2}日.{0,25}?\d{1,2}[:：]\d{2}[-~～—－–]\d{1,2}[:：]\d{2})',text)
        if not match:
            logging.info('华理公告无明确逐场日期/时刻，不编造排期：%s',title)
            continue
        place=re.search(r'(?:大会地点|会议地点|举办地点|活动地点)[：:]?(.{1,90}?)(?=参会单位|参会人才|三、|3[、.]|$)',text)
        result.append(event('华东理工大学',match[1],match[1],'',title,place[1] if place else '',link,'招聘会'))
    return result


def shiep():
    result = []
    for path, kind in [('/teachin', '宣讲会'), ('/jobfair', '招聘会')]:
        next_url = 'https://career.shiep.edu.cn' + path
        visited = set()
        while next_url:
            if next_url in visited or len(visited) >= 100:
                raise ValueError('上电分页重复或超过100页')
            visited.add(next_url)
            html = request(next_url)
            for value in re.findall(r'unzip\("([A-Za-z0-9+/=]+)"\)', html):
                raw = zlib.decompress(base64.b64decode(value)).decode()
                if raw.startswith('view2d'):
                    raw = raw.split(None, 1)[1]
                decoded = base64.b64decode(raw).decode()
                if decoded.startswith('view1d'):
                    decoded = decoded.split(None, 1)[1]
                html += decoded
            soup = BeautifulSoup(html, 'html.parser')
            found = 0
            for box in soup.select('ul.infoList'):
                a = box.select_one('a[href*="/view/id/"]')
                if not a:
                    continue
                cells = box.find_all('li', recursive=False)
                if len(cells) < 3:
                    raise ValueError('上电活动行字段已变化')
                when = cells[-1].get_text(' ', strip=True)
                found += 1
                if not times(when):
                    logging.warning('上电活动未公布开始时刻，暂不纳入：%s', a.get_text(strip=True))
                    continue
                result.append(event('上海电力大学', when, when, '', a.get_text(' ',strip=True),
                                    cells[-2].get_text(' ',strip=True), a['href'], kind))
            if not found and not re.search('暂无|没有.*记录|无相关', soup.get_text()):
                raise ValueError(f'上电{kind}列表未解析到明确数据')
            next_a = soup.select_one('.pages .next:not(.disabled) a')
            next_url = urllib.parse.urljoin(next_url,next_a['href']) if next_a else None
            # 初始化时获取近期排期；不强求一次补全多年历史。
            if result and max(e['d'] for e in result[-max(found,1):]) < months(dt.datetime.now(TZ).date())[0]+'-01':
                break
    return result


def ecupl():
    """日程页为空时从官网招聘会公告正文采集，绝不使用新闻发布日期作举办日。"""
    school = '华东政法大学'
    url = 'https://jy.ecupl.edu.cn/16921/list.htm'
    soup = BeautifulSoup(request(url),'html.parser')
    links = {urllib.parse.urljoin(url,a['href']):a.get('title') or a.get_text(strip=True)
             for a in soup.select('a[href*="/page.htm"]')
             if re.search('邀请函|招聘会|双选会|招聘活动服务指南',a.get('title') or a.get_text())}
    rows = []
    for link,title in links.items():
        detail = BeautifulSoup(request(link),'html.parser')
        content = detail.select_one('.wp_articlecontent')
        if not content:
            continue
        text = content.get_text(' ',strip=True)
        # 优先公告明确的活动时间行，避免后文报到时间和报名截止日期。
        match = re.search(r'(?:活动时间|举办时间|时间)[：:]\s*(.{0,100})',text)
        when = match[1] if match else ''
        if not times(when):
            # 学期服务指南中的首场招聘会单独有完整活动日期。
            match = re.search(r'(20\d{2}年\s*\d+月\s*\d+日.{0,40}\d{1,2}:\d{2}[-－–]\d{1,2}:\d{2})',text)
            when = match[1] if match else ''
        if not when or not times(when):
            continue
        day = date(re.sub(r'\s+','',when))
        if not day:
            month_day = re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*日',when)
            year_match = re.search(r'/(20\d{2})/',link)
            if not month_day or not year_match:
                continue
            year=int(year_match[1])
            day=dt.date(year,int(month_day[1]),int(month_day[2])).isoformat()
        place = re.search(r'(?:地点|场地)[：:]\s*(.{1,90}?)(?=0[2-9][.、]|二、|三、|$)',text)
        venue = place[1].strip() if place else ''
        if not venue:
            match = re.search(r'在([^。]{1,50}?(?:体育馆|报告厅|教室))召开',text)
            venue=match[1] if match else ''
        rows.append(event(school,day,when,'',title,venue,link,'招聘会'))
    if not rows:
        raise ValueError('官网公告未提供可验证的活动日期及开始时间')
    return rows


def collect(school, today):
    if school in CAREER: return career(school, today)
    if school in SPA: return spa(school, today)
    if school in ('东华大学','上海外国语大学'): return jsonp_school(school)
    if school == '同济大学': return tongji()
    if school == '华东理工大学': return ecust()
    if school == '上海电力大学': return shiep()
    return ecupl()


def identity(e):
    # 官方详情ID+举办日，允许同一活动多日排期；当日改时间/地点时更新同一记录。
    # 无逐场ID的公开列表回退记录，在完整刷新窗口中整体替换未结束场次。
    link = e['link']
    if e['link'] == SOURCES[e['school']]:
        return (e['school'],e['co'],e['d'],e['start'])
    return (e['school'],link,e['d'])


def reconcile(old, fresh, successful, now):
    """保留已结束历史；成功学校的当前/未来公开窗口以最新列表为准。
    被最新列表撤下或改期的旧未来场次进入审计归档，不继续误显示，也不宣称已取消。
    """
    window = months(now.date())
    end_month = dt.date.fromisoformat(window[-1]+'-01')
    upper = end_month.replace(day=calendar.monthrange(end_month.year,end_month.month)[1]).isoformat()
    old_map = {identity(e):e for e in old}
    fresh_map = {identity(e):e for e in fresh}
    retired = []
    for key,e in list(old_map.items()):
        upcoming = (e['d'],e['start']) >= (now.date().isoformat(),now.strftime('%H:%M'))
        if e['school'] in successful and upcoming and e['d'] <= upper and key not in fresh_map:
            retired.append(dict(record=e,reason='本轮完整公开列表未再列出，可能改期或撤下；不认定已取消',checked_at=now.isoformat()))
            del old_map[key]
    old_map.update(fresh_map)
    return sorted(old_map.values(),key=lambda e:(e['d'],e['start'],e['school'],e['co'])),retired


def public_error(exc):
    text = str(exc)
    if 'No Data' in text:
        return '官方日程列表暂未提供可解析排期，请查看学校官网。'
    if '登录' in text or '验证码' in text:
        return '官网要求登录或验证，本轮跳过。'
    if any(word in text for word in ('BrowserType', 'Timeout', 'timeout', 'Executable')):
        return '动态网页加载失败，本轮保留旧记录；详细原因见运行日志。'
    if 'HTTP Error 403' in text:
        return '官网对自动更新服务器返回403拒绝访问，沿用已核实记录；不代表本轮成功。'
    if 'urlopen' in text or 'HTTP Error' in text:
        return '官网连接失败，本轮保留旧记录；详细原因见运行日志。'
    return text[:160]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--school', choices=list(SOURCES))
    parser.add_argument('--render-only', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    now = dt.datetime.now(TZ)
    cache = ROOT/'data/events.json'
    old = json.loads(cache.read_text()) if cache.exists() else []
    supplement_path = ROOT/'data/supplements.json'
    supplements = json.loads(supplement_path.read_text()) if supplement_path.exists() else []
    fallback_path = ROOT/'data/verified-fallback.json'
    fallback = json.loads(fallback_path.read_text()) if fallback_path.exists() else {}
    statusfile = ROOT/'data/status.json'
    prior = json.loads(statusfile.read_text()) if statusfile.exists() else {}
    states = prior.get('schools', {})
    for e in old:
        if e['school'] == '东华大学':
            e['link'] = e['link'].replace('ejob.dhu.edu.cn/preaching.html','ejob.dhu.edu.cn/page/preaching.html').replace('ejob.dhu.edu.cn/recruitment.html','ejob.dhu.edu.cn/page/recruitment.html')
    fresh, successful = [],set()
    if not args.render_only:
        targets = [args.school] if args.school else list(SOURCES)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(collect,s,now.date()):s for s in targets}
            for future in concurrent.futures.as_completed(jobs):
                school = jobs[future]
                try:
                    rows = future.result()
                    if not isinstance(rows,list):
                        raise ValueError('官网列表结果类型异常')
                    for e in rows:
                        assert set(e)=={'d','start','end','co','venue','school','type','link'}
                        dt.date.fromisoformat(e['d'])
                        assert e['school']==school
                    fresh.extend(rows)
                    successful.add(school)
                    states[school] = dict(ok=True,count=len(rows),last_success=now.isoformat(),last_attempt=now.isoformat(),error='',month_counts={m:sum(e['d'].startswith(m) for e in rows) for m in months(now.date())})
                    logging.info('%s: %d 场，本月 %d 场',school,len(rows),sum(e['d'].startswith(now.strftime('%Y-%m')) for e in rows))
                except Exception as exc:
                    verified = fallback.get('schools',{}).get(school,{})
                    cached_rows = verified.get('events',[])
                    fresh.extend(cached_rows)
                    states[school] = dict(ok=False,count=0,last_success=states.get(school,{}).get('last_success'),last_attempt=now.isoformat(),error=public_error(exc),fallback_count=len(cached_rows),fallback_verified_at=verified.get('verified_at'))
                    logging.error('%s: %s；保留历史及%d条独立核实缓存',school,exc,len(cached_rows))
    # 补录优先级低于官网本轮更新，同一详情+举办日不重复。
    records,retired = reconcile(old+supplements,fresh,successful,now) if not args.render_only else (sorted({identity(e):e for e in old+supplements}.values(),key=lambda e:(e['d'],e['start'],e['school'],e['co'])),[])
    for school in SOURCES:
        state=states.setdefault(school,{})
        state['supplement_count']=sum(e['school']==school for e in supplements)
        state['retained_count']=sum(e['school']==school for e in records)
        state['current_month_count']=sum(e['school']==school and e['d'].startswith(now.strftime('%Y-%m')) for e in records)
        state['coverage']='官方通知公告，不涵盖登录后或公众号排期' if school=='华东政法大学' else '官网公开列表与月历，非全校所有渠道的保证'
    failed = [school for school in SOURCES if not states.get(school,{}).get('ok')]
    audit = dict(checked_at=now.isoformat(),before=len(old),after=len(records),current_month=now.strftime('%Y-%m'),current_month_before=sum(e['d'].startswith(now.strftime('%Y-%m')) for e in old),current_month_after=sum(e['d'].startswith(now.strftime('%Y-%m')) for e in records),retired_future_count=len(retired),failed=failed)
    status = dict(attempted_at=prior.get('attempted_at',now.isoformat()) if args.render_only else now.isoformat(),schools=states,sources=SOURCES,total=len(records),window=months(now.date()),run_url=os.environ.get('RUN_URL',prior.get('run_url','')),current_month_count=audit['current_month_after'],end_dates={**prior.get('end_dates',{}),**END_DATES},coverage_note='只收录可核实的官方公开排期；源站改期、撤下或访问失败均会影响覆盖。')
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    statusfile.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
    if not args.render_only:
        (ROOT/'data/audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
        retiredfile=ROOT/'data/retired-future.json'
        previous=json.loads(retiredfile.read_text()) if retiredfile.exists() else []
        retiredfile.write_text(json.dumps(previous+retired,ensure_ascii=False,indent=2)+'\n')
    template = (ROOT/'template.html').read_text()
    safe = lambda value: json.dumps(value,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    (ROOT/'index.html').write_text(template.replace('__EVENTS__',safe(records)).replace('__STATUS__',safe(status)))
    report=f'本月 {audit["current_month_after"]} 场（更新前 {audit["current_month_before"]}）；历史及现有共 {len(records)} 场；来源失败 {len(failed)} 校；旧未来排期移至审计归档 {len(retired)} 条'
    logging.info(report)
    summary=os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a') as f:
            f.write(report+'\n\n|学校|自动检查|本轮数量|本月收录|最近成功|\n|---|---|---|---|---|\n')
            for school in SOURCES:
                v=states[school]
                f.write(f'|{school}|{"成功" if v.get("ok") else "失败，沿用已核实缓存"}|{v.get("count",0)}|{v["current_month_count"]}|{v.get("last_success") or "尚未成功"}|\n')
    (ROOT/'data/health.json').write_text(json.dumps(dict(failed=failed),ensure_ascii=False)+'\n')
    return 1 if failed and not args.render_only else 0

if __name__ == '__main__':
    raise SystemExit(main())
