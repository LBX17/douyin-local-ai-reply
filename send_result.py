"""Conservative interpretation of the currently supported IM response schema."""
import json
from dataclasses import dataclass

from google.protobuf.message import DecodeError
from static import Response_pb2


@dataclass(frozen=True)
class SendResult:
    status: str
    message: str


def parse_send_result(response):
    if response.status_code != 200:
        return SendResult('failed', f'发送接口返回 HTTP {response.status_code}')
    if not response.content:
        return SendResult('unconfirmed', '发送接口返回空响应，无法确认结果；不会自动重发')
    content = response.content.lstrip()
    if content.startswith(b'{'):
        try:
            data = json.loads(content)
        except (ValueError, UnicodeError):
            return SendResult('unconfirmed', '发送接口返回无法解析的 JSON；不会自动重发')
        if isinstance(data, dict):
            candidates = [data]
            if isinstance(data.get('data'), dict):
                candidates.append(data['data'])
            codes = [entry[key] for entry in candidates for key in ('status_code', 'error_code')
                     if key in entry]
            if codes and any(str(code) != '0' for code in codes):
                return SendResult('failed', '抖音接口拒绝发送，请检查登录状态和发送权限')
            if codes:
                return SendResult('accepted', '抖音接口已确认接受发送请求')
        return SendResult('unconfirmed', '发送接口没有可识别的结果码；不会自动重发')
    envelope = Response_pb2.Response()
    try:
        envelope.ParseFromString(response.content)
    except DecodeError:
        return SendResult('unconfirmed', '发送接口返回未识别的响应；不会自动重发')
    if envelope.error_desc:
        return SendResult('failed', '抖音接口返回发送错误，请检查登录状态和发送权限')
    # The repository schema does not define the send acknowledgement body.
    # A successful HTTP response alone cannot establish message delivery.
    return SendResult('unconfirmed', '发送请求已提交，当前协议无法确认送达；不会自动重发')
