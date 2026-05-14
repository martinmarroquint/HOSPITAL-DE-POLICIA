"""
ROLES DEL SISTEMA - FUENTE ÚNICA DE VERDAD
Jerarquía: super_admin → admin_cliente → admin_empresa → jefe → usuario → visitante → escaner
"""

ROLES_SISTEMA = {
    'super_admin': {
        'nombre': 'Super Administrador',
        'nivel': 200,
        'color': '#0F172A',
        'descripcion': 'Control total del sistema. Gestiona clientes.',
        'es_jefatura': True,
        'sistema': True,
    },
    'admin_cliente': {
        'nombre': 'Administrador de Cliente',
        'nivel': 150,
        'color': '#1E3A5F',
        'descripcion': 'Gestiona todas las empresas de un cliente',
        'es_jefatura': True,
        'sistema': True,
    },
    'admin_empresa': {
        'nombre': 'Administrador de Empresa',
        'nivel': 100,
        'color': '#2563EB',
        'descripcion': 'Control total de una empresa',
        'es_jefatura': True,
        'sistema': True,
    },
    'jefe': {
        'nombre': 'Jefe / Supervisor',
        'nivel': 70,
        'color': '#3FB4B4',
        'descripcion': 'Gestiona su equipo y visitantes',
        'es_jefatura': True,
        'sistema': True,
    },
    'usuario': {
        'nombre': 'Usuario',
        'nivel': 30,
        'color': '#6B7280',
        'descripcion': 'Usuario estándar',
        'es_jefatura': False,
        'sistema': True,
    },
    'visitante': {
        'nombre': 'Visitante',
        'nivel': 10,
        'color': '#8B5CF6',
        'descripcion': 'Acceso mínimo',
        'es_jefatura': False,
        'sistema': True,
    },
    'escaner': {
        'nombre': 'Escaner QR',
        'nivel': 5,
        'color': '#EF4444',
        'descripcion': 'Solo escanea QR',
        'es_jefatura': False,
        'sistema': True,
    },
}

# Grupos de roles para permisos
ROLES_ADMIN = ['super_admin', 'admin_cliente', 'admin_empresa']
ROLES_JEFE = ['jefe']
ROLES_PUEDEN_CREAR_PUBLICACIONES = ['admin_empresa', 'jefe']
ROLES_PUEDEN_GESTIONAR_USUARIOS = ['admin_cliente', 'admin_empresa']
ROLES_PUEDEN_CONFIGURAR = ['admin_empresa']
ROLES_PUEDEN_APROBAR_SOLICITUDES = ['admin_empresa', 'jefe']
ROLES_PUEDEN_VER_REPORTES = ['admin_empresa', 'jefe']
ROLES_SOLO_LECTURA = ['usuario', 'visitante']
ROLES_SOLO_ESCANER = ['escaner']

TODOS_LOS_ROLES = list(ROLES_SISTEMA.keys())
ROLES_JEFATURA = [k for k, v in ROLES_SISTEMA.items() if v.get('es_jefatura')]

SQL_ROLES_DEFAULT = """
INSERT INTO config_roles (nombre, descripcion, nivel, color, sistema, activo, es_jefatura, alcance_global, empresa_id) VALUES
('super_admin', 'Super Administrador - Control total del sistema', 200, '#0F172A', true, true, true, true, NULL),
('admin_cliente', 'Administrador de Cliente - Gestiona todas las empresas del cliente', 150, '#1E3A5F', true, true, true, true, NULL),
('admin_empresa', 'Administrador de Empresa - Control total de la empresa', 100, '#2563EB', true, true, true, false, NULL),
('jefe', 'Jefe / Supervisor - Gestiona su equipo', 70, '#3FB4B4', true, true, true, false, NULL),
('usuario', 'Usuario estándar', 30, '#6B7280', true, true, false, false, NULL),
('visitante', 'Visitante - Acceso mínimo', 10, '#8B5CF6', true, true, false, false, NULL),
('escaner', 'Escaner QR - Solo escanea', 5, '#EF4444', true, true, false, false, NULL);
"""