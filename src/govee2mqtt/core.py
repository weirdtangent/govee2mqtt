from .base import Base
from .mixins.govee import GoveeMixin
from .mixins.govee_api import GoveeAPIMixin
from .mixins.helpers import HelpersMixin
from .mixins.loops import LoopsMixin
from .mixins.mqtt import MqttMixin
from .mixins.publish import PublishMixin
from .mixins.refresh import RefreshMixin


class Govee2Mqtt(
    HelpersMixin,
    PublishMixin,
    GoveeMixin,
    GoveeAPIMixin,
    RefreshMixin,
    LoopsMixin,
    MqttMixin,
    Base,
):
    pass
