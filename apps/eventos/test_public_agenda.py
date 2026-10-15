"""Public agenda for DyA Social Studio: only public fields, only upcoming open events, token required."""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.academias.models import Academia
from .models import Evento, ReciboEvento


@override_settings(DYA_INTEGRATION_API_TOKEN='test-integration-only', DEBUG=True, APPDANZA_PUBLIC_URL='https://appdanza.com')
class PublicAgendaTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.bml = Academia.objects.create(pk=3, nombre='Bachatamanía', slug='bachatamania', divisa='COP')
        self.distrito = Academia.objects.create(pk=4, nombre='Distrito Social', slug='distrito-social', divisa='COP')
        self.inactive = Academia.objects.create(pk=5, nombre='Cerrada', slug='cerrada', divisa='COP', activo=False)
        self.ok = Evento.objects.create(academia=self.distrito, nombre='Social Distrito', slug='social-distrito',
                                        fecha=now + timedelta(days=2), ubicacion='Distrito Social', estado='REGISTRO_ONLINE',
                                        precio_preventa=25000, precio_puerta=30000)
        self.door = Evento.objects.create(academia=self.bml, nombre='Bachatamanía Noche', slug='bml-noche',
                                          fecha=now + timedelta(days=5), ubicacion='Bogotá', estado='REGISTRO_PUERTA')
        Evento.objects.create(academia=self.bml, nombre='Pasado', slug='pasado', fecha=now - timedelta(days=2),
                              ubicacion='X', estado='REGISTRO_ONLINE')
        Evento.objects.create(academia=self.bml, nombre='Finalizado', slug='fin', fecha=now + timedelta(days=1),
                              ubicacion='X', estado='FINALIZADO')
        Evento.objects.create(academia=self.inactive, nombre='De academia inactiva', slug='x',
                              fecha=now + timedelta(days=1), ubicacion='X', estado='REGISTRO_ONLINE')
        ReciboEvento.objects.create(evento=self.ok, comprador_nombre='Dato privado', comprador_telefono='3001234567',
                                    origen='PUERTA', precio_unitario_aplicado=100, monto_total=100,
                                    payment_status='LEGACY', revisado_por_admin=True)
        self.url = reverse('dya_public_agenda')
        self.auth = {'HTTP_AUTHORIZATION': 'Bearer test-integration-only'}

    def test_requires_token(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.get(self.url, HTTP_AUTHORIZATION='Bearer wrong').status_code, 401)

    def test_only_upcoming_public_events_of_active_academies(self):
        data = self.client.get(self.url, **self.auth).json()
        names = [e['name'] for e in data['events']]
        self.assertEqual(names, ['Social Distrito', 'Bachatamanía Noche'])
        first = data['events'][0]
        self.assertEqual(first['academy'], {'slug': 'distrito-social', 'name': 'Distrito Social'})
        self.assertEqual(first['registration_url'],
                         'https://appdanza.com' + reverse('eventos:registro_publico', kwargs={'slug_academia': 'distrito-social', 'evento_slug': 'social-distrito'}))
        self.assertEqual((first['price_presale'], first['price_door']), ('25000.00', '30000.00'))
        self.assertEqual(data['events'][1]['registration_url'], '')   # door only: no online link

    def test_never_leaks_private_data(self):
        body = self.client.get(self.url, **self.auth).content.decode()
        for private in ('Dato privado', '3001234567', 'monto', 'recibo', 'deuda', 'nequi', 'banco'):
            self.assertNotIn(private.lower(), body.lower())

    def test_filter_by_academy_and_write_methods_refused(self):
        data = self.client.get(self.url, {'academy': 'bachatamania'}, **self.auth).json()
        self.assertEqual([e['name'] for e in data['events']], ['Bachatamanía Noche'])
        self.assertEqual(self.client.post(self.url, **self.auth).status_code in (403, 405), True)

    @override_settings(DEBUG=False)
    def test_https_required_in_production(self):
        self.assertEqual(self.client.get(self.url, **self.auth).status_code, 403)
