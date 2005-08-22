require File.dirname(__FILE__) + '/../test_helper'
require 'hellanzb_controller'

# Re-raise errors caught by the controller.
class HellanzbController; def rescue_action(e) raise e end; end

class HellanzbControllerTest < Test::Unit::TestCase
  def setup
    @controller = HellanzbController.new
    @request    = ActionController::TestRequest.new
    @response   = ActionController::TestResponse.new
  end

  # Replace this with your real tests.
  def test_truth
    assert true
  end
end
