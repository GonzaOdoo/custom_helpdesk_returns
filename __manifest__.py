# -*- coding: utf-8 -*-
{
    'name': "Retornos personalizados en Helpdesk",

    'summary': """
        Módulo para gestionar retornos personalizados en Helpdesk
       """,

    'description': """
        Este módulo permite gestionar retornos personalizados en el módulo de Helpdesk, integrando funcionalidades específicas para manejar devoluciones de productos y servicios.
    """,

    'author': "GonzaOdoo",
    'website': "http://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/odoo/addons/base/module/module_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '1.0',

    # any module necessary for this one to work correctly
    'depends': ['stock','quality_control','helpdesk','helpdesk_stock','product','purchase'],
    # always loaded
    "data": ["security/ir.model.access.csv",
             "views/defectos.xml",
             "views/helpdesk_team.xml",
             "views/helpdesl_product.xml",
            ],
}
