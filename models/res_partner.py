from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero, float_round
import logging

_logger = logging.getLogger(__name__)
class ResPartner(models.Model):
    _inherit = 'res.partner'

    support_email = fields.Char(string='Email reclamos')
    sales_email = fields.Char(string='Email ventas')
    