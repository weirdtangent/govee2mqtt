from .mixins.helpers import HelpersMixin
from .mixins.mqtt import MqttMixin
from .mixins.publish import PublishMixin
from .mixins.govee import GoveeMixin
from .mixins.govee_api import GoveeAPIMixin
from .mixins.refresh import RefreshMixin
from .mixins.loops import LoopsMixin
from .base import Base


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
