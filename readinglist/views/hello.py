from cornice import Service
from pyramid.security import NO_PERMISSION_REQUIRED
from readinglist import __version__ as VERSION


hello = Service(name="hello", path='/', description="Welcome")


@hello.get(permission=NO_PERMISSION_REQUIRED)
def get_hello(request):
    """Return information regarding the current instance."""
    data = dict(
        hello='readinglist',
        version=VERSION,
        url=request.host_url,
        documentation="https://readinglist.rtfd.org/"
    )

    eos = get_eos(request)
    if eos:
        data['eos'] = eos

    return data


def get_eos(request):
    return request.registry.settings.get('readinglist.eos', '').strip() or None
