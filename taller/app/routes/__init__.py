"""Registro de blueprints."""


def registrar_blueprints(app):
    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .clientes import bp as clientes_bp
    from .mecanico import bp as mecanico_bp
    from .ordenes import bp as ordenes_bp
    from .red import bp as red_bp
    from .reportes import bp as reportes_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(clientes_bp, url_prefix="/clientes")
    app.register_blueprint(ordenes_bp, url_prefix="/ordenes")
    app.register_blueprint(mecanico_bp, url_prefix="/mecanico")
    app.register_blueprint(reportes_bp, url_prefix="/reportes")
    app.register_blueprint(red_bp)
