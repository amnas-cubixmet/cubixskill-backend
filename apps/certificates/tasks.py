from celery import shared_task
from certificates.models import Certificate, CertPDFMode
from certificates.services import CertificateService

@shared_task
def generate_persistent_certificate_pdf_task(certificate_id: str):
    """
    Celery task to generate and store persistent PDF in S3/media storage asynchronously.
    """
    try:
        certificate = Certificate.objects.get(id=certificate_id)
        if certificate.pdf_storage_mode == CertPDFMode.STORED and not certificate.pdf_media:
            CertificateService.store_persistent_pdf(certificate)
            return f"Persistent PDF generated for certificate {certificate.certificate_number}"
        return f"Certificate {certificate_id} does not require persistent PDF generation."
    except Certificate.DoesNotExist:
        return f"Certificate {certificate_id} not found."
