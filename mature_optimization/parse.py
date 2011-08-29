import re
from datetime import datetime

from django.conf import settings

class BaseParser(object):
    """
    Base class not to be used directly.
    """
    pattern = None
    date_format = None
    date_ignore_pattern = None

    @classmethod
    def parse_line(cls, line):
        """
        Parse one line of the log file and output a dictionary of the parsed
        values.
        """
        regex = re.compile(cls.pattern)
        m = regex.search(line)
        if m:
            data = m.groupdict()
            data = cls.post_process(data)
            if cls.date_format:
                data['time'] = cls.convert_time(data['time'])
            else:
                data['time'] = datetime.now()
            return data
        else:
            return {}

    @classmethod
    def convert_time(cls, time_str):
        """
        Convert date string to datetime object
        """
        if cls.date_ignore_pattern:
            time_str = re.sub(cls.date_ignore_pattern, '', time_str)
        return datetime.strptime(time_str, cls.date_format)

    @classmethod
    def post_process(cls, data):
        """
        Implement this in the subclass. Accept/return parsed data structure.
        """
        return data

    @classmethod
    def parse_file(cls, fp):
        with open(fp, 'r') as logfile:
            for line in logfile:
                data = cls.parse_line(line)
                if len(data) == 0:
                    # We hit the end of the file
                    continue
                yield data

class NginxRequestTimesParser(BaseParser):
    """
    Used to parse the following Nginx log format:

    log_format request_times 'IP=$remote_addr,
                              TL=$time_local,
                              DN=$host,
                              RQ=$request,
                              HR=$http_referer,
                              HU=$http_user_agent,
                              CS=$cookie_sessionid,
                              UT=$upstream_response_time,
                              RT=$request_time,
                              US=$upstream_status,
                              SC=$status';
    """
    date_format = "%d/%b/%Y:%H:%M:%S"
    date_ignore_pattern = r' -\d{4}'
    pattern = ','.join([
            r'^IP=(?P<ip>.*[^,])',
            r'TL=(?P<time>.*[^,])',
            r'DN=(?P<host>.*[^,])',
            r'RQ=(?P<request>.*[^,])',
            r'HR=(?P<http_referer>.*[^,])',
            # user agents have commas sometimes
            r'HU=(?P<http_user_agent>.*[^,])',
            r'CS=(?P<cookie_sessionid>.*[^,])',
            r'UT=(?P<upstream_response_time>.*[^,])',
            r'RT=(?P<request_time>.*[^,])',
            r'US=(?P<upstream_status>.*[^,])',
            r'SC=(?P<status>.*?)\s*$',
            ])

    @classmethod
    def post_process(cls, data):
        """
        Convert request string into http method and url
        """
        request_string = data['request']
        request_pattern = r'(?P<http_method>GET|HEAD|POST) (?P<url>\S+)'
        m = re.search(request_pattern, request_string)
        if m:
            newdata = m.groupdict()
            data.update(newdata)

        data['request_time'] = float(data['request_time'])

        # If the upstream response was '-' then Nginx bailed out and didn't wait
        if data['upstream_response_time'] == '-':
            # TODO: This should really be factored out to a conf module with
            # a proper default in one place.
            slow_threshold = getattr(settings, 'MO_SLOW_PAGE_SECONDS', 7.0)

            # If the response is a 499 and the page wasn't slow, then the
            # user probably bailed for a reason other than the page being slow.
            # Usually, this is because of a double-click, so let's set the
            # upstream time to the request time, effectively ignoring this
            # request for slowness purposes
            if (data['status'] == '499'and
                data['request_time'] < slow_threshold):
                data['upstream_response_time'] = data['request_time']
            else:
                data['upstream_response_time'] = 90.0
        else:
            data['upstream_response_time'] = float(
                data['upstream_response_time'])

        return data

