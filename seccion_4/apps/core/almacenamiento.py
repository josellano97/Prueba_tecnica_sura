"""Almacenamiento de estáticos: nombres con hash (caché larga) incluidos los import de módulos JS."""
from whitenoise.storage import CompressedManifestStaticFilesStorage


class EstaticosVersionados(CompressedManifestStaticFilesStorage):
    # Reescribe `import ... from "./formato.js"` a la versión con hash, para que un despliegue
    # nuevo nunca mezcle módulos viejos y nuevos en la caché del navegador.
    support_js_module_import_aggregation = True
