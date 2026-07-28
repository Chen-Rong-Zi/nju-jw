#!/usr/bin/python3
import subprocess
from datetime          import datetime
from requests          import get, Session, Session
from lxml              import etree

from returns.iterables import Fold
from returns.pointfree import map_, bind
from returns.pipeline  import pipe, flow, is_successful
from returns.result    import ResultE, Success, Failure, safe

from multivalue        import MIterator

def trace(x):
    print('DEBUG: ' + str(type(x)) + '  ' + str(x))
    return x

# get_html :: str -> ResultE str
@safe
def get_html(url):
    return get(url, verify=False).text

from requests.adapters import HTTPAdapter
import ssl

class TLSAdapter(HTTPAdapter):
    import ssl
from requests.adapters import HTTPAdapter

class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        # 强制使用 TLS 1.2 或更高版本
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        # 设置加密套件（允许更广泛的兼容性）
        context.set_ciphers('DEFAULT:@SECLEVEL=1')
        kwargs['ssl_context'] = context
        return super(TLSAdapter, self).init_poolmanager(*args, **kwargs)

@safe
def get_html(url):
    command = ['curl', '-k', url]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        return result.stdout
    else:
        raise Exception(f"Error fetching URL: {result.stderr}")

# safe_head collect a -> a
@safe
def safe_head(collect):
    if collect:
        return collect[0]
    else:
        return ""

# safe_getx :: str -> node -> ResultE x
def safe_getx(path):
    # breakpoint()
    return safe(lambda node : node.xpath(path))

# get_newsboard_node :: node -> ResultE List node
get_newsboard_node = safe_getx('/html/body/div[7]/div/div/div[2]/div/div[2]/div/div/div[1]/ul/li')

parse_time         = pipe(safe_getx('.//text()'), bind(safe_head), map_(lambda datestring : datetime.strptime(datestring, '%Y-%m-%d')))
parse_tags         = pipe(safe_getx('.//text()'), bind(safe_head), map_(lambda tags : [t for t in tags.split('，') if t]))

parse_title = pipe(
    safe_getx('./a'),
    bind(safe_head),
    map_(lambda x : (x.get('title'), x.get('href'))),
)

# parse_node :: node -> ResultE (tags, title, time)
def parse_node(node):
    tag_node, title_node, time_node = node.getchildren()
    return Fold.collect(
        (parse_tags(tag_node),
         parse_title(title_node),
         parse_time(time_node)),
        ResultE.from_value(())
    ).map(
        lambda tu : (tu[0], tu[1][0], tu[2], 'https://jw.nju.edu.cn/ggtz/list1.htm' + tu[1][1])
    )

# extract_news :: HTML -> ResultE MIterator (tags, title, time)
def extract_news(html):
    return flow(
        html,                           # HTML
        get_newsboard_node,             # ResultE List node
        map_(MIterator),                # ResultE MIterator node
        map_(map_(parse_node)),         # ResultE MIterator ResultE (tags, title, time)
    )

# ResultE MIterator (tags, title, time)
def handler(tu):
    if is_successful(tu):
        # Fold.collect(tu.unwrap(), Success(()))\
            # .map(lambda i: print('\t'.join(str(b) for b in i)))\
            # .alt(lambda i: print(i))
        for i in Fold.collect(tu.unwrap(), Success(())).unwrap():
            print('\t'.join(str(b) for b in i))
    else:
        print(tu)

def main():
    flow(
        'https://jw.nju.edu.cn/ggtz/list1.htm',         # str
        get_html,                                       # ResultE str
        map_(etree.HTML),                               # ResultE HTML
        bind(extract_news),                             # ResultE MIterator (tags, title, time)
        handler
    )

def parse_html_items(html: str) -> list[dict]:
    """
    Parse HTML page and return list of items.
    Each item: {tags: list[str], title: str, time: str, url: str}

    This function is importable by main.py for HTML fallback.
    """
    tree = etree.HTML(html)
    nodes = get_newsboard_node(tree)
    if not is_successful(nodes):
        return []

    results = []
    for node in nodes.unwrap():
        parsed = parse_node(node)
        if is_successful(parsed):
            tags, title, time, url = parsed.unwrap()
            results.append({
                'tags': tags,
                'title': title,
                'time': time.strftime('%Y-%m-%d') if hasattr(time, 'strftime') else str(time),
                'url': url,
            })
    return results


if __name__ == '__main__':
    main()

