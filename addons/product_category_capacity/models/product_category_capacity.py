from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductCategoryCapacity(models.Model):
    _name = 'product.category.capacity'
    _description = 'Product Category Monthly Capacity'
    _order = 'category_id, year desc'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True
    )
    
    category_id = fields.Many2one(
        'product.category',
        string='Product Category',
        required=True,
        ondelete='cascade'
    )
    
    # Keep as selection but simplify - just one option
    month = fields.Selection([
        ('month', 'Month'),
    ], string='Period', required=True, default='month')
    
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.today().year
    )
    
    # Monthly capacity - user input
    monthly_capacity = fields.Float(
        string='Monthly Capacity',
        required=True,
        help='Maximum monthly production capacity for this category'
    )
    
    # Capacity unit
    capacity_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True,
        default=lambda self: self.env.ref('uom.product_uom_unit', raise_if_not_found=False),
        help='Unit of measure for capacity (pieces, hours, kg, etc.)'
    )
    
    # Additional fields
    notes = fields.Text(
        string='Notes',
        help='Additional notes about this capacity'
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )
    
    @api.depends('category_id', 'year')
    def _compute_display_name(self):
        for record in self:
            if record.category_id and record.year:
                record.display_name = f"{record.category_id.name} - {record.year}"
            else:
                record.display_name = "New Capacity Record"
    
    @api.constrains('monthly_capacity')
    def _check_capacity_positive(self):
        for record in self:
            if record.monthly_capacity <= 0:
                raise ValidationError("Monthly capacity must be greater than zero.")
    
    @api.constrains('year')
    def _check_year_validity(self):
        for record in self:
            current_year = fields.Date.today().year
            if record.year < current_year - 10 or record.year > current_year + 10:
                raise ValidationError("Year must be within reasonable range (±10 years from current year).")
    
    @api.constrains('category_id', 'year')
    def _check_unique_category_year(self):
        for record in self:
            existing = self.search([
                ('category_id', '=', record.category_id.id),
                ('year', '=', record.year),
                ('id', '!=', record.id)
            ])
            if existing:
                raise ValidationError(f"Capacity for {record.category_id.name} in {record.year} already exists.")
    
    @api.model
    def get_monthly_capacity(self, category_id, year):
        """Get monthly capacity for a specific category and year"""
        capacity = self.search([
            ('category_id', '=', category_id),
            ('year', '=', year)
        ], limit=1)
        return capacity.monthly_capacity if capacity else 0.0