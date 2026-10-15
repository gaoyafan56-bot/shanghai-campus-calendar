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
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; ShanghaiCampusCalendar/1.0)'}


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
    match = re.search(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})', str(value or ''))
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
    return dict(d=day, start=starts[0], end=ends[0] if ends else (starts[1] if len(starts)>1 else ''),
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
    """让官网自己解析公开加密响应，再从可见日历和悬浮表格读取。
    不依赖生产版 Vue 已移除的调试属性，不读取凭证或硬编码密钥。
    """
    from playwright.sync_api import sync_playwright
    result = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale='zh-CN', timezone_id='Asia/Shanghai')
        try:
            origin = 'https://' + urllib.parse.urlparse(SOURCES[school]).netloc
            # 四校同一公开系统中的宣讲、招聘会入口；逐场链接仍回退学校入口。
            for route in ('xjh-list', 'fairs'):
                page.goto(origin + '/home/recruit-info/' + route,
                          wait_until='domcontentloaded', timeout=60000)
                page.wait_for_selector('.calendar-grid', timeout=30000)
                page.wait_for_function("!document.querySelector('.loading-overlay')", timeout=30000)
                for offset in (-1, 0, 1, 2):
                    nav = page.locator('.month-navigation button')
                    (nav.first if offset == -1 else nav.last).click()
                    page.wait_for_function("!document.querySelector('.loading-overlay')", timeout=30000)
                    for cell in page.locator('.date-cell.has-events').all():
                        label = cell.get_attribute('aria-label') or ''
                        day = date(label)
                        if not day or day[:7] not in mm:
                            continue
                        cell.hover()
                        table_rows = page.locator('.el-popper:visible .el-table__body tbody tr')
                        table_rows.first.wait_for(state='visible', timeout=10000)
                        for row in table_rows.all():
                            cells = row.locator('td')
                            if cells.count() < 3:
                                raise ValueError('公开日历悬浮表格列发生变化')
                            start_time = cells.nth(0).inner_text().strip()
                            title = cells.nth(1).inner_text().strip()
                            venue = cells.nth(2).inner_text().strip()
                            if not times(start_time) or not title:
                                raise ValueError('公开日历活动缺少明确开始时间或名称')
                            result.append(dict(hdrq=day, hdkssj=start_time, hdjssj='',
                                hdmc=title, hddd=venue,
                                hdlx='招聘会' if route=='fairs' else '宣讲会'))
        finally:
            browser.close()
    if not result:
        raise ValueError('动态日历未读取到可验证场次，暂不认定为零活动')
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
    school = '华东政法大学'
    html = request(SOURCES[school])
    if '<!-- No Data -->' in html:
        raise ValueError('官方日程列表返回 No Data，暂未发现可验证的逐场排期')
    soup = BeautifulSoup(html, 'html.parser')
    links = {urllib.parse.urljoin(SOURCES[school],a['href']):a.get('title') or a.get_text(strip=True)
             for a in soup.select('a[href*="/page.htm"]')}
    if not links:
        raise ValueError('华政日程页面结构需重新适配；保留官方日程入口')
    rows = []
    for url, title in links.items():
        detail = BeautifulSoup(request(url),'html.parser')
        content = detail.select_one('.wp_articlecontent')
        if not content:
            raise ValueError('华政详情正文结构已变化')
        text = content.get_text(' ',strip=True)
        # 必须有明确活动时间标签，不使用列表上的新闻发布日期。
        match = re.search(r'(?:活动时间|举办时间|宣讲时间|招聘时间|会议时间|时间)[：:]\s*(.{0,120})',text)
        if not match or not date(match[1]) or not times(match[1]):
            raise ValueError('华政排期正文未找到明确活动日期及开始时间')
        place = re.search(r'(?:地点|场地)[：:]\s*([^。；;]{1,80})',text)
        rows.append(event(school,match[1],match[1],'',title,place[1] if place else '',SOURCES[school]))
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
    # 同一详情代表一场：改时间/地点时更新，而非重复旧版本。
    # 列表回退无稳定ID，用学校+标题+日期+开始时间避免合并多场。
    return (e['school'], e['link']) if e['link'] != SOURCES[e['school']] else (e['school'],e['co'],e['d'],e['start'])


def public_error(exc):
    text = str(exc)
    if 'No Data' in text:
        return '官方日程列表暂未提供可解析排期，请查看学校官网。'
    if '登录' in text or '验证码' in text:
        return '官网要求登录或验证，本轮跳过。'
    if any(word in text for word in ('BrowserType', 'Timeout', 'timeout', 'Executable')):
        return '动态网页加载失败，本轮保留旧记录；详细原因见运行日志。'
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
    statusfile = ROOT/'data/status.json'
    prior = json.loads(statusfile.read_text()) if statusfile.exists() else {}
    states = prior.get('schools', {})
    for e in old:
        if e['school'] == '东华大学':
            e['link'] = e['link'].replace('ejob.dhu.edu.cn/preaching.html','ejob.dhu.edu.cn/page/preaching.html').replace('ejob.dhu.edu.cn/recruitment.html','ejob.dhu.edu.cn/page/recruitment.html')
    merged = {identity(e):e for e in old}
    failed = []
    if not args.render_only:
        targets = [args.school] if args.school else list(SOURCES)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(collect,s,now.date()):s for s in targets}
            for future in concurrent.futures.as_completed(jobs):
                school = jobs[future]
                try:
                    fresh = future.result()
                    for e in fresh:
                        merged[identity(e)] = e
                    states[school] = dict(ok=True,count=len(fresh),last_success=now.isoformat(),error='')
                    logging.info('%s: %d 场', school, len(fresh))
                except Exception as exc:
                    failed.append(school)
                    states[school] = dict(ok=False,count=0,last_success=states.get(school,{}).get('last_success'),error=public_error(exc))
                    logging.error('%s: %s；保留旧数据',school,exc)
    failed = [school for school in SOURCES if not states.get(school,{}).get('ok')]
    records = sorted(merged.values(),key=lambda e:(e['d'],e['start'],e['school'],e['co']))
    status = dict(attempted_at=prior.get('attempted_at',now.isoformat()) if args.render_only else now.isoformat(),schools=states,sources=SOURCES,
                  total=len(records),window=months(now.date()),run_url=__import__('os').environ.get('RUN_URL',''))
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    statusfile.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
    template = (ROOT/'template.html').read_text()
    safe = lambda value: json.dumps(value,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    (ROOT/'index.html').write_text(template.replace('__EVENTS__',safe(records)).replace('__STATUS__',safe(status)))
    report = f'总计 {len(records)} 场；本轮失败 {len(failed)} 校：'+('、'.join(failed) or '无')
    logging.info(report)
    summary = __import__('os').environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a') as f:
            f.write(report+'\n\n|学校|状态|本轮条数|\n|---|---|---|\n')
            for s in SOURCES:
                v=states.get(s,{})
                f.write(f'|{s}|{"成功" if v.get("ok") else "未更新"}|{v.get("count",0)}|\n')
    # 先写入可用结果，工作流随后发布，再以失败状态触发 GitHub 邮件。
    (ROOT/'data/health.json').write_text(json.dumps(dict(failed=failed),ensure_ascii=False)+'\n')
    return 1 if failed and not args.render_only else 0

if __name__ == '__main__':
    raise SystemExit(main())
