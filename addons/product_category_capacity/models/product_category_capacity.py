from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import timedelta


class ProductCategoryCapacity(models.Model):
    _name = 'product.category.capacity'
    _description = 'Product Category Monthly Capacity'
    _order = 'category_id, year desc, month desc'
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
    
    # Time period - focusing on monthly
    month = fields.Selection([
        ('01', 'January'),
        ('02', 'February'),
        ('03', 'March'),
        ('04', 'April'),
        ('05', 'May'),
        ('06', 'June'),
        ('07', 'July'),
        ('08', 'August'),
        ('09', 'September'),
        ('10', 'October'),
        ('11', 'November'),
        ('12', 'December'),
    ], string='Month', required=True)
    
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
    
    # Computed fields for reference
    date_start = fields.Date(
        string='Month Start',
        compute='_compute_month_dates',
        store=True
    )
    
    date_end = fields.Date(
        string='Month End',
        compute='_compute_month_dates',
        store=True
    )
    
    @api.depends('category_id', 'month', 'year')
    def _compute_display_name(self):
        month_names = dict(self._fields['month'].selection)
        for record in self:
            if record.category_id and record.month and record.year:
                month_name = month_names.get(record.month, record.month)
                record.display_name = f"{record.category_id.name} - {month_name} {record.year}"
            else:
                record.display_name = "New Capacity Record"
    
    @api.depends('month', 'year')
    def _compute_month_dates(self):
        for record in self:
            if record.month and record.year:
                # First day of the month
                record.date_start = fields.Date.from_string(f"{record.year}-{record.month}-01")
                # Last day of the month
                if record.month == '12':
                    next_month_start = fields.Date.from_string(f"{record.year + 1}-01-01")
                else:
                    next_month_num = str(int(record.month) + 1).zfill(2)
                    next_month_start = fields.Date.from_string(f"{record.year}-{next_month_num}-01")
                
                # Calculate last day of current month
                record.date_end = next_month_start - timedelta(days=1)
            else:
                record.date_start = False
                record.date_end = False
    
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
    
    @api.constrains('category_id', 'month', 'year')
    def _check_unique_category_month(self):
        for record in self:
            existing = self.search([
                ('category_id', '=', record.category_id.id),
                ('month', '=', record.month),
                ('year', '=', record.year),
                ('id', '!=', record.id)
            ])
            if existing:
                raise ValidationError(f"Capacity for {record.category_id.name} in {record.month}/{record.year} already exists.")
    
    @api.model
    def get_monthly_capacity(self, category_id, month, year):
        """Get monthly capacity for a specific category, month, and year"""
        capacity = self.search([
            ('category_id', '=', category_id),
            ('month', '=', month),
            ('year', '=', year)
        ], limit=1)
        return capacity.monthly_capacity if capacity else 0.0