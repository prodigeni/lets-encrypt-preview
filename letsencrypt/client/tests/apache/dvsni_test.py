"""Test for letsencrypt.client.apache.dvsni."""
import os
import pkg_resources
import unittest
import shutil

import mock
import zope.component

from letsencrypt.client import challenge_util
from letsencrypt.client import client
from letsencrypt.client import CONFIG

from letsencrypt.client.tests.apache import config_util


class DvsniPerformTest(unittest.TestCase):

    def setUp(self):
        from letsencrypt.client.apache import dvsni

        self.temp_dir, self.config_dir, self.work_dir = config_util.dir_setup(
            "debian_apache_2_4/two_vhost_80")

        self.ssl_options = config_util.setup_apache_ssl_options(self.config_dir)

        # Final slash is currently important
        self.config_path = os.path.join(
            self.temp_dir, "debian_apache_2_4/two_vhost_80/apache2/")

        config = config_util.get_apache_configurator(
            self.config_path, self.config_dir, self.work_dir, self.ssl_options)

        self.sni = dvsni.ApacheDvsni(config)

        rsa256_file = pkg_resources.resource_filename(
            "letsencrypt.client.tests", 'testdata/rsa256_key.pem')
        rsa256_pem = pkg_resources.resource_string(
            "letsencrypt.client.tests", 'testdata/rsa256_key.pem')

        auth_key = client.Client.Key(rsa256_file, rsa256_pem)
        self.challs = []
        self.challs.append(challenge_util.DvsniChall(
            "encryption-example.demo",
            "jIq_Xy1mXGN37tb4L6Xj_es58fW571ZNyXekdZzhh7Q",
            "37bc5eb75d3e00a19b4f6355845e5a18",
            auth_key))
        self.challs.append(challenge_util.DvsniChall(
            "letsencrypt.demo",
            "uqnaPzxtrndteOqtrXb0Asl5gOJfWAnnx6QJyvcmlDU",
            "59ed014cac95f77057b1d7a1b2c596ba",
            auth_key))

    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        shutil.rmtree(self.config_dir)
        shutil.rmtree(self.work_dir)

    def test_perform0(self):
        resp = self.sni.perform()
        self.assertTrue(resp is None)

    @mock.patch("letsencrypt.client.apache.configurator."
                "ApacheConfigurator.restart")
    @mock.patch("letsencrypt.client.challenge_util.dvsni_gen_cert")
    def test_perform1(self, mock_dvsni_gen_cert, mock_restart):
        chall = self.challs[0]
        self.sni.add_chall(chall)
        mock_dvsni_gen_cert.return_value = "randomS1"
        responses = self.sni.perform()

        self.assertEqual(mock_dvsni_gen_cert.call_count, 1)
        calls = mock_dvsni_gen_cert.call_args_list
        expected_call_list = [
            (self.sni.get_cert_file(chall.nonce), chall.domain,
             chall.r_b64, chall.nonce, chall.key)
        ]

        for i in range(len(expected_call_list)):
            for j in range(len(expected_call_list[0])):
                self.assertEqual(calls[i][0][j], expected_call_list[i][j])

        self.assertEqual(
            len(self.sni.config.parser.find_dir(
                "Include", self.sni.challenge_conf)),
            1)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["s"], "randomS1")

    @mock.patch("letsencrypt.client.apache.configurator."
                "ApacheConfigurator.restart")
    @mock.patch("letsencrypt.client.challenge_util.dvsni_gen_cert")
    def test_perform2(self, mock_dvsni_gen_cert, mock_restart):
        for chall in self.challs:
            self.sni.add_chall(chall)

        mock_dvsni_gen_cert.side_effect = ["randomS0", "randomS1"]
        responses = self.sni.perform()

        self.assertEqual(mock_dvsni_gen_cert.call_count, 2)
        calls = mock_dvsni_gen_cert.call_args_list
        expected_call_list = []

        for chall in self.challs:
            expected_call_list.append(
                (self.sni.get_cert_file(chall.nonce), chall.domain,
                 chall.r_b64, chall.nonce, chall.key))

        for i in range(len(expected_call_list)):
            for j in range(len(expected_call_list[0])):
                self.assertEqual(calls[i][0][j], expected_call_list[i][j])

        self.assertEqual(
            len(self.sni.config.parser.find_dir(
                "Include", self.sni.challenge_conf)),
            1)
        self.assertEqual(len(responses), 2)
        for i in range(2):
            self.assertEqual(responses[i]["s"], "randomS%d" % i)

    def test_mod_config(self):
        from letsencrypt.client.apache.obj import Addr
        for chall in self.challs:
            self.sni.add_chall(chall)
        v_addr1 = [Addr(("1.2.3.4", "443")), Addr(("5.6.7.8", "443"))]
        v_addr2 = [Addr(("127.0.0.1", "443"))]
        ll_addr = []
        ll_addr.append(v_addr1)
        ll_addr.append(v_addr2)
        self.sni._mod_config(ll_addr)  # pylint: disable=protected-access
        self.sni.config.save()

        self.sni.config.parser.find_dir("Include", self.sni.challenge_conf)
        vh_match = self.sni.config.aug.match(
            "/files" + self.sni.challenge_conf + "//VirtualHost")

        vhs = []
        for match in vh_match:
            # pylint: disable=protected-access
            vhs.append(self.sni.config._create_vhost(match))
        self.assertEqual(len(vhs), 2)
        for vhost in vhs:
            if vhost.addrs == set(v_addr1):
                self.assertEqual(
                    vhost.names,
                    set([str(self.challs[0].nonce + CONFIG.INVALID_EXT)]))
            else:
                self.assertEqual(vhost.addrs, set(v_addr2))
                self.assertEqual(
                    vhost.names,
                    set([str(self.challs[1].nonce + CONFIG.INVALID_EXT)]))
