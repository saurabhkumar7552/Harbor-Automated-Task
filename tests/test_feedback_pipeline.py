"""Feedback-first generation regressions: no live providers, no task execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stem_factory import contracts
from stem_factory.generation import GenerationFactory
from stem_factory.manifest_package import traceability_report
from tests.test_manifest_generation import configuration, manifest, bundle
from tests.test_workflow import FakeAdapter, FakeValidator
from tests.fixtures import review


def adapters(final=None, review_result=None):
    def author(index, prompt, schema):
        if set(schema.get('properties', {})) == {'proposal', 'implementation'}:
            return final() if final else {'proposal': manifest(), 'implementation': bundle()}
        return manifest()
    a = FakeAdapter(author)
    r = FakeAdapter(lambda *args: review_result if review_result is not None else review(False))
    return {'author': a, 'implementer': a, 'reviewer': r}


class FeedbackPipeline(unittest.TestCase):
    def test_failed_review_still_finalizes_once_then_packages(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d), adapters()
            with patch('subprocess.Popen', side_effect=AssertionError('offline fixtures only')):
                result = GenerationFactory(c, adapters=a).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 3)
            self.assertEqual(len(a['author'].calls), 2)
            self.assertEqual(len(a['reviewer'].calls), 1)
            self.assertIn('Specify units', a['author'].calls[-1])
            self.assertIn('does not require verified immutable digests', a['reviewer'].calls[0])
            self.assertEqual(result['candidates'][0]['status'], 'accepted')

    def test_relative_artifact_names_and_grouped_traceability_do_not_reject(self):
        def final():
            b = bundle()
            b['instruction'] = 'In /work, provide analyze.sh and result.tsv. Summarize orbital data and reject malformed records.'
            b['requirements_traceability'] = [{'requirement': 'Grouped paraphrase of both requirements', 'tests': ['test_orbit']}]
            return {'proposal': manifest(), 'implementation': b}
        with tempfile.TemporaryDirectory() as d:
            c = configuration(d)
            result = GenerationFactory(c, adapters=adapters(final)).run(1)
            self.assertEqual(result['accepted'], 1)
            row = result['candidates'][0]
            self.assertTrue(any('Coverage not established' in w for w in row['packaging_warnings']))
            public = (Path(row['package_path'])/'instruction.md').read_text(encoding='utf-8')
            self.assertIn('`/work/analyze.sh`', public)
            evidence = json.loads((Path(row['package_path'])/'authoring/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(evidence['traceability']['coverage_status'], 'incomplete')

    def test_requirement_ids_establish_declared_coverage_without_exact_sentences(self):
        b = bundle()
        b['requirements_traceability'] = [{'requirement': f'R{i:03d}', 'tests': ['test_orbit']}
                                          for i in range(1, 3)]
        check = traceability_report(manifest(), b)
        self.assertEqual(check['unverified_requirements'], [])
        self.assertEqual(check['warnings'], [])
        self.assertEqual(check['coverage_status'], 'declared')

    def test_final_proposal_and_implementation_update_together(self):
        def final():
            p, b = manifest(), bundle()
            p['functional_requirements'] = ['Revised requirement after reviewer feedback']
            b['requirements_traceability'] = [{'requirement': 'R001', 'tests': ['test_orbit']}]
            return {'proposal': p, 'implementation': b}
        with tempfile.TemporaryDirectory() as d:
            result = GenerationFactory(configuration(d), adapters=adapters(final)).run(1)
            self.assertEqual(result['accepted'], 1)
            evidence = json.loads((Path(result['candidates'][0]['package_path'])/'authoring/evidence.json').read_text(encoding='utf-8'))
            self.assertNotEqual(evidence['initial_proposal']['functional_requirements'], evidence['proposal']['functional_requirements'])

    def test_invalid_packages_are_preserved_not_rejected_and_do_not_loop(self):
        def final():
            b = bundle()
            b['reference_files'][0]['path'] = '../escape'
            return {'proposal': manifest(), 'implementation': b}
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d), adapters(final)
            c.limits['max_candidates'] = None
            result = GenerationFactory(c, adapters=a).run(1)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(result['needs_attention'], 1)
            self.assertEqual(len(result['candidates']), 1)
            self.assertEqual(result['calls_reserved'], 3)
            row = result['candidates'][0]
            self.assertEqual(row['package_validation_status'], 'invalid')
            self.assertTrue((Path(row['package_path'])/'diagnostics.json').exists())
            self.assertFalse((c.output/'escape').exists())
            resumed = GenerationFactory(c, adapters=a).run(1)
            self.assertEqual(resumed['calls_reserved'], 3)

    def test_malformed_reviewer_response_is_retained_and_final_author_still_runs(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d), adapters(review_result={'verdict': 'invalid'})
            result = GenerationFactory(c, adapters=a).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertIn('error', a['author'].calls[-1])
            self.assertEqual(result['candidates'][0]['final_findings']['initial_review']['verdict'], 'unavailable')

    def test_five_candidates_all_preserved_when_offline_validation_fails(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d, count=5), adapters()
            c.limits['max_candidates'] = 5
            result = GenerationFactory(c, adapters=a, validator=FakeValidator(False)).run(5)
            self.assertEqual(result['accepted'], 0)
            self.assertEqual(result['needs_attention'], 5)
            self.assertEqual(result['completed_candidates'], 5)
            self.assertEqual(result['calls_reserved'], 15)
            self.assertTrue(all(row['status'] == 'needs_attention' for row in result['candidates']))
            self.assertEqual(len(list((c.output/'drafts').iterdir())), 5)

    def test_five_valid_packages_take_fifteen_calls_despite_failed_reviews(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d, count=5), adapters()
            c.limits['max_candidates'] = 5
            def author(index, prompt, schema):
                p = manifest(task_id=f'orbit-sample-{(index + 1) // 2}')
                if set(schema['properties']) == {'proposal', 'implementation'}:
                    return {'proposal': p, 'implementation': bundle()}
                return p
            a['author'].function = author
            result = GenerationFactory(c, adapters=a).run(5)
            self.assertEqual(result['accepted'], 5)
            self.assertEqual(result['needs_attention'], 0)
            self.assertEqual(result['calls_reserved'], 15)
            self.assertEqual(len(a['reviewer'].calls), 5)
            self.assertEqual(len(list((c.output/'accepted').iterdir())), 5)

    def test_publication_crash_resumes_without_paid_requests(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d), adapters()
            with patch('stem_factory.feedback_pipeline.publish', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                GenerationFactory(c, adapters=a).run(1)
            result = GenerationFactory(c, adapters=a).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 3)

    def test_initial_environment_diagnostics_do_not_consume_feedback_fix(self):
        with tempfile.TemporaryDirectory() as d:
            c, a = configuration(d), adapters()
            original = a['author'].function
            def author(index, prompt, schema):
                value = original(index, prompt, schema)
                if 'proposal' not in schema['properties']:
                    value['environment_plan']['base_image'] = 'alpine:latest'
                return value
            a['author'].function = author
            result = GenerationFactory(c, adapters=a).run(1)
            self.assertEqual(result['accepted'], 1)
            self.assertEqual(result['calls_reserved'], 3)
            self.assertIn('base_image requires', a['reviewer'].calls[0])
            self.assertIn('Specify units', a['author'].calls[-1])

    def test_malformed_final_response_is_preserved_without_replacement_or_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            c = configuration(d)
            c.limits['max_candidates'] = None
            a = adapters(lambda: {'incomplete': True})
            result = GenerationFactory(c, adapters=a).run(1)
            self.assertEqual(result['needs_attention'], 1)
            self.assertEqual(result['calls_reserved'], 3)
            row = result['candidates'][0]
            self.assertEqual(row['diagnostic_phase'], 'finalize')
            self.assertEqual(row['package_validation_status'], 'not_run')
            self.assertTrue((Path(row['package_path'])/'diagnostics.json').exists())


if __name__ == '__main__':
    unittest.main()
