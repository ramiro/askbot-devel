"""
Settings for content categories. These categories will be
applicable to:
 * Tags
 * Questions
 * Users
"""
from askbot.conf.settings_wrapper import settings
from askbot.deps import livesettings
from django.utils.translation import ugettext as _


CATEGORIES = livesettings.ConfigurationGroup(
                    'CATEGORIES',
                    _('Categories settings'),
                    ordering=2
                )

settings.register(
    livesettings.BooleanValue(
        CATEGORIES,
        'ENABLE_CATEGORIES',
        default=False,
        description=_('Check to enable categories for content'),
    )
)

settings.register(
    livesettings.IntegerValue(
        CATEGORIES,
        'CATEGORIES_MAX_TREE_DEPTH',
        default=3,
        description=_('Number of levels in the categories hierarchy tree'),
    )
)

settings.register(
    livesettings.StringValue(
        CATEGORIES,
        'TOP_LEVEL_CATEGORY_NAME',
        default='Everything',
        description=_('Name of the category located at the root of the categories tree')
    )
)

