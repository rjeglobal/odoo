from odoo import models, fields, api


class ProductCategory(models.Model):
    _inherit = 'product.category'
    
    capacity_ids = fields.One2many(
        'product.category.capacity',
        'category_id',
        string='Monthly Capacity Records'
    )
    
    capacity_count = fields.Integer(
        string='Capacity Records',
        compute='_compute_capacity_count'
    )
    
    current_month_capacity = fields.Float(
        string='Current Month Capacity',
        compute='_compute_current_month_capacity'
    )
    
    @api.depends('capacity_ids')
    def _compute_capacity_count(self):
        for category in self:
            category.capacity_count = len(category.capacity_ids)
    
    @api.depends('capacity_ids')
    def _compute_current_month_capacity(self):
        current_month = fields.Date.today().strftime('%m')
        current_year = fields.Date.today().year
        
        for category in self:
            current_capacity = category.capacity_ids.filtered(
                lambda c: c.month == current_month and c.year == current_year
            )
            category.current_month_capacity = current_capacity.monthly_capacity if current_capacity else 0.0
    
    def action_view_capacity_planning(self):
        """Open capacity planning view for this category"""
        action = self.env.ref('product_category_capacity.product_category_capacity_action').read()[0]
        action['domain'] = [('category_id', '=', self.id)]
        action['context'] = {
            'default_category_id': self.id,
            'search_default_current_year': True
        }
        return action